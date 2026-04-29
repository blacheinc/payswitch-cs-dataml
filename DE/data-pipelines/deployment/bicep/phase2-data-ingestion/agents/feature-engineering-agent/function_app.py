"""
Feature Engineering Agent - Azure Function
Enterprise-Grade Automated Feature Generation & Drift Monitoring

This agent generates features from validated data, stores them in Feast Feature Store,
monitors feature drift, and publishes to the next stage.
"""

import azure.functions as func
import logging
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Any, Optional
import pandas as pd
import numpy as np
from scipy import stats
from azure.servicebus import ServiceBusClient, ServiceBusMessage
from azure.keyvault.secrets import SecretClient
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
import hashlib

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================
# Configuration
# ============================================================

class Config:
    """Configuration from environment variables"""

    SERVICE_BUS_NAMESPACE = os.getenv('SERVICE_BUS_NAMESPACE')
    KEY_VAULT_URL = os.getenv('KEY_VAULT_URL')
    STORAGE_ACCOUNT_NAME = os.getenv('STORAGE_ACCOUNT_NAME')
    FEAST_REGISTRY_PATH = os.getenv('FEAST_REGISTRY_PATH', 'gs://feast-registry')

    # Drift thresholds
    PSI_WARNING_THRESHOLD = float(os.getenv('PSI_WARNING', '0.1'))
    PSI_CRITICAL_THRESHOLD = float(os.getenv('PSI_CRITICAL', '0.2'))
    KS_WARNING_THRESHOLD = float(os.getenv('KS_WARNING', '0.05'))
    KS_CRITICAL_THRESHOLD = float(os.getenv('KS_CRITICAL', '0.1'))

    # Topics
    INPUT_TOPIC = 'data-quality-checked'
    OUTPUT_TOPIC = 'features-engineered'
    DRIFT_TOPIC = 'drift-detected'

# ============================================================
# Feature Definitions
# ============================================================

FEATURE_DEFINITIONS = {
    # Demographic features
    'age': {
        'calculation': lambda data: calculate_age(data.get('date_of_birth')),
        'type': 'int',
        'category': 'demographic'
    },
    'age_squared': {
        'calculation': lambda data: calculate_age(data.get('date_of_birth')) ** 2,
        'type': 'int',
        'category': 'demographic'
    },
    'age_group': {
        'calculation': lambda data: bin_age(calculate_age(data.get('date_of_birth'))),
        'type': 'string',
        'category': 'demographic'
    },

    # Financial features
    'debt_to_income_ratio': {
        'calculation': lambda data: safe_divide(
            data.get('existing_loans_balance', 0),
            data.get('monthly_income', 1)
        ),
        'type': 'float',
        'category': 'financial'
    },
    'loan_to_income_ratio': {
        'calculation': lambda data: safe_divide(
            data.get('requested_amount', 0),
            data.get('monthly_income', 1) * 12
        ),
        'type': 'float',
        'category': 'financial'
    },
    'disposable_income': {
        'calculation': lambda data: data.get('monthly_income', 0) - data.get('monthly_expenses', 0),
        'type': 'float',
        'category': 'financial'
    },
    'savings_rate': {
        'calculation': lambda data: safe_divide(
            data.get('monthly_income', 0) - data.get('monthly_expenses', 0),
            data.get('monthly_income', 1)
        ),
        'type': 'float',
        'category': 'financial'
    },
    'expense_ratio': {
        'calculation': lambda data: safe_divide(
            data.get('monthly_expenses', 0),
            data.get('monthly_income', 1)
        ),
        'type': 'float',
        'category': 'financial'
    },

    # Credit features
    'credit_utilization': {
        'calculation': lambda data: safe_divide(
            data.get('credit_used', 0),
            data.get('credit_limit', 1)
        ),
        'type': 'float',
        'category': 'credit'
    },

    # Interaction features
    'income_times_age': {
        'calculation': lambda data: data.get('monthly_income', 0) * calculate_age(data.get('date_of_birth')),
        'type': 'float',
        'category': 'interaction'
    },

    # Risk indicators
    'high_dti_flag': {
        'calculation': lambda data: 1 if safe_divide(data.get('existing_loans_balance', 0), data.get('monthly_income', 1)) > 0.4 else 0,
        'type': 'int',
        'category': 'risk'
    },
    'negative_disposable_income_flag': {
        'calculation': lambda data: 1 if (data.get('monthly_income', 0) - data.get('monthly_expenses', 0)) < 0 else 0,
        'type': 'int',
        'category': 'risk'
    }
}

# ============================================================
# Helper Functions
# ============================================================

def calculate_age(date_of_birth: str) -> int:
    """Calculate age from date of birth"""
    try:
        dob = pd.to_datetime(date_of_birth)
        today = pd.Timestamp.now()
        age = (today - dob).days // 365
        return age
    except:
        return 0

def safe_divide(numerator: float, denominator: float) -> float:
    """Safe division avoiding divide by zero"""
    if denominator == 0:
        return 0.0
    return numerator / denominator

def bin_age(age: int) -> str:
    """Bin age into groups"""
    if age < 25:
        return '18-24'
    elif age < 35:
        return '25-34'
    elif age < 45:
        return '35-44'
    elif age < 55:
        return '45-54'
    elif age < 65:
        return '55-64'
    else:
        return '65+'

def calculate_psi(expected: pd.Series, actual: pd.Series, bins: int = 10) -> float:
    """
    Calculate Population Stability Index (PSI)

    PSI < 0.1: No significant change
    PSI 0.1-0.2: Moderate change
    PSI > 0.2: Significant change (retraining needed)
    """
    try:
        # Create bins
        breakpoints = np.quantile(expected, np.linspace(0, 1, bins + 1))
        expected_bins = pd.cut(expected, bins=breakpoints, labels=False, duplicates='drop')
        actual_bins = pd.cut(actual, bins=breakpoints, labels=False, duplicates='drop')

        # Calculate percentages
        expected_pct = expected_bins.value_counts(normalize=True).sort_index()
        actual_pct = actual_bins.value_counts(normalize=True).sort_index()

        # Align indices
        expected_pct, actual_pct = expected_pct.align(actual_pct, fill_value=0.0001)

        # Calculate PSI
        psi = np.sum((actual_pct - expected_pct) * np.log(actual_pct / expected_pct))

        return float(psi)
    except:
        return 0.0

def calculate_ks_statistic(dist1: pd.Series, dist2: pd.Series) -> float:
    """Calculate Kolmogorov-Smirnov statistic for drift detection"""
    try:
        stat, _ = stats.ks_2samp(dist1, dist2)
        return float(stat)
    except:
        return 0.0

# ============================================================
# Feature Engineering Agent Class
# ============================================================

class FeatureEngineeringAgent:
    """
    Enterprise-grade feature engineering agent

    Features:
    - Automated feature generation
    - Feature store integration (Feast)
    - Drift monitoring (PSI, KS)
    - Feature versioning
    - Feature lineage tracking
    """

    def __init__(self):
        """Initialize the Feature Engineering Agent"""
        self.config = Config()
        self.credential = DefaultAzureCredential()

        # Initialize clients
        self.service_bus_client = None
        self.blob_service_client = None

        # Feature version
        self.feature_version = 'v1.0'

        logger.info("Feature Engineering Agent initialized")

    def _get_service_bus_client(self) -> ServiceBusClient:
        """Get Service Bus client (lazy initialization)"""
        if not self.service_bus_client:
            conn_string = os.getenv('SERVICE_BUS_CONNECTION_STRING')
            self.service_bus_client = ServiceBusClient.from_connection_string(conn_string)
        return self.service_bus_client

    def generate_features(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate all features from input data

        Args:
            data: Input data dictionary

        Returns:
            Dictionary of features
        """
        features = {}

        for feature_name, feature_def in FEATURE_DEFINITIONS.items():
            try:
                value = feature_def['calculation'](data)
                features[feature_name] = {
                    'value': value,
                    'type': feature_def['type'],
                    'category': feature_def['category'],
                    'version': self.feature_version,
                    'computed_at': datetime.utcnow().isoformat()
                }
                logger.debug(f"Generated feature {feature_name}: {value}")
            except Exception as e:
                logger.warning(f"Error generating feature {feature_name}: {str(e)}")
                features[feature_name] = {
                    'value': None,
                    'error': str(e),
                    'version': self.feature_version
                }

        return features

    def calculate_feature_hash(self, features: Dict[str, Any]) -> str:
        """Calculate hash of features for deduplication"""
        feature_str = json.dumps(features, sort_keys=True)
        return hashlib.sha256(feature_str.encode()).hexdigest()

    def store_features(self, record_id: str, features: Dict[str, Any]):
        """
        Store features in Feature Store (Feast)

        In production, this would write to:
        - Online Store: Redis (for real-time serving)
        - Offline Store: Data Lake (for training)
        """
        try:
            # TODO: Implement Feast feature store integration
            # For now, log features
            logger.info(f"Storing features for record {record_id}")

            # Feature store would do:
            # 1. Write to Redis (online store) for real-time serving
            # 2. Write to Data Lake (offline store) for training
            # 3. Update feature metadata (lineage, version, statistics)

            pass
        except Exception as e:
            logger.error(f"Error storing features: {str(e)}")
            raise

    def monitor_drift(self, features: Dict[str, Any], historical_features: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
        """
        Monitor feature drift using PSI and KS statistics

        Args:
            features: Current features
            historical_features: Historical feature distribution

        Returns:
            Drift monitoring report
        """
        drift_report = {
            'timestamp': datetime.utcnow().isoformat(),
            'features_monitored': [],
            'drift_detected': False,
            'severity': 'none',
            'metrics': {}
        }

        if historical_features is None or len(historical_features) < 100:
            logger.info("Insufficient historical data for drift monitoring")
            return drift_report

        # Monitor numeric features
        numeric_features = [
            name for name, data in features.items()
            if data.get('type') in ['int', 'float'] and data.get('value') is not None
        ]

        for feature_name in numeric_features:
            try:
                current_value = features[feature_name]['value']

                if feature_name not in historical_features.columns:
                    continue

                historical_dist = historical_features[feature_name].dropna()

                if len(historical_dist) < 10:
                    continue

                # Calculate PSI (comparing current value to historical distribution)
                # For single value, we compare to the distribution
                current_series = pd.Series([current_value] * len(historical_dist))
                psi = calculate_psi(historical_dist, current_series)

                # Calculate KS statistic
                current_sample = pd.Series([current_value] * min(100, len(historical_dist)))
                ks_stat = calculate_ks_statistic(historical_dist, current_sample)

                drift_report['features_monitored'].append(feature_name)
                drift_report['metrics'][feature_name] = {
                    'psi': round(psi, 4),
                    'ks_statistic': round(ks_stat, 4),
                    'mean_shift': round((current_value - historical_dist.mean()) / historical_dist.std(), 4) if historical_dist.std() > 0 else 0
                }

                # Check thresholds
                if psi > self.config.PSI_CRITICAL_THRESHOLD or ks_stat > self.config.KS_CRITICAL_THRESHOLD:
                    drift_report['drift_detected'] = True
                    drift_report['severity'] = 'critical'
                    logger.warning(f"Critical drift detected in {feature_name}: PSI={psi:.4f}, KS={ks_stat:.4f}")
                elif psi > self.config.PSI_WARNING_THRESHOLD or ks_stat > self.config.KS_WARNING_THRESHOLD:
                    drift_report['drift_detected'] = True
                    if drift_report['severity'] != 'critical':
                        drift_report['severity'] = 'warning'
                    logger.info(f"Warning: Drift detected in {feature_name}: PSI={psi:.4f}, KS={ks_stat:.4f}")

            except Exception as e:
                logger.warning(f"Error monitoring drift for {feature_name}: {str(e)}")

        return drift_report

    def process_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main feature engineering processing function

        Args:
            data: Input data from Data Quality Agent

        Returns:
            Feature engineering report
        """
        record_id = data.get('record_id', 'unknown')
        logger.info(f"Processing features for record_id: {record_id}")

        # 1. Generate features
        features = self.generate_features(data['data'] if 'data' in data else data)

        # 2. Calculate feature hash
        feature_hash = self.calculate_feature_hash(features)

        # 3. Store features (Feast)
        self.store_features(record_id, features)

        # 4. Monitor drift (load historical features from storage)
        # TODO: Load historical features from Data Lake or PostgreSQL
        historical_features = None  # Placeholder
        drift_report = self.monitor_drift(features, historical_features)

        # 5. Build feature engineering report
        feature_report = {
            'record_id': record_id,
            'timestamp': datetime.utcnow().isoformat(),
            'features': features,
            'feature_hash': feature_hash,
            'feature_version': self.feature_version,
            'feature_count': len(features),
            'drift_report': drift_report
        }

        logger.info(f"Generated {len(features)} features for record {record_id}")

        return feature_report

    def publish_to_service_bus(self, message: Dict[str, Any], topic_name: str):
        """Publish message to Service Bus topic"""
        try:
            sender = self._get_service_bus_client().get_topic_sender(topic_name)

            service_bus_message = ServiceBusMessage(
                body=json.dumps(message),
                content_type='application/json',
                message_id=message.get('record_id', str(datetime.utcnow().timestamp()))
            )

            sender.send_messages(service_bus_message)
            logger.info(f"Published message to {topic_name}")

        except Exception as e:
            logger.error(f"Error publishing to Service Bus: {str(e)}")
            raise

# ============================================================
# Azure Function Entry Point
# ============================================================

app = func.FunctionApp()

@app.service_bus_topic_trigger(
    arg_name="message",
    topic_name="data-quality-checked",
    subscription_name="feature-engineering-agent-sub",
    connection="SERVICE_BUS_CONNECTION_STRING"
)
def feature_engineering_agent_trigger(message: func.ServiceBusMessage):
    """
    Azure Function triggered by Service Bus message

    Args:
        message: Service Bus message from 'data-quality-checked' topic
    """
    try:
        # Parse message
        message_body = message.get_body().decode('utf-8')
        data = json.loads(message_body)

        logger.info(f"Received message: {message.message_id}")

        # Initialize agent
        agent = FeatureEngineeringAgent()

        # Process data
        feature_report = agent.process_data(data)

        # Publish to next topic
        agent.publish_to_service_bus(
            {
                'record_id': feature_report['record_id'],
                'features': feature_report['features'],
                'feature_version': feature_report['feature_version'],
                'feature_hash': feature_report['feature_hash']
            },
            Config.OUTPUT_TOPIC
        )

        # Check for drift and publish alert if needed
        if feature_report['drift_report']['drift_detected']:
            agent.publish_to_service_bus(
                {
                    'record_id': feature_report['record_id'],
                    'drift_report': feature_report['drift_report'],
                    'timestamp': feature_report['timestamp']
                },
                Config.DRIFT_TOPIC
            )
            logger.warning(f"Drift detected: {feature_report['drift_report']['severity']}")

        logger.info(f"Message processed successfully: {message.message_id}")

    except Exception as e:
        logger.error(f"Error processing message: {str(e)}", exc_info=True)
        raise

@app.timer_trigger(
    arg_name="timer",
    schedule="0 0 3 * * *",  # Daily at 3 AM UTC
    run_on_startup=False
)
def feature_drift_monitoring(timer: func.TimerRequest):
    """
    Scheduled function to monitor feature drift across all features

    Runs daily to:
    - Calculate PSI/KS for all features
    - Generate drift reports
    - Trigger retraining if needed
    """
    logger.info("Running daily feature drift monitoring")

    # TODO: Implement comprehensive drift monitoring
    # - Load last 30 days of features
    # - Calculate PSI/KS for each feature
    // - Generate drift dashboard
    # - Alert if critical drift detected
    # - Trigger Model Training Agent if needed

    logger.info("Feature drift monitoring completed")
