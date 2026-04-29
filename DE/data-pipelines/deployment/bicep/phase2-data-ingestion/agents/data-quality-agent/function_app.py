"""
Data Quality Agent - Azure Function
Enterprise-Grade Data Validation & Quality Scoring

This agent validates incoming data from various sources, performs quality checks,
detects outliers, and scores data quality before passing to Feature Engineering Agent.
"""

import azure.functions as func
import logging
import json
import os
from datetime import datetime
from typing import Dict, List, Tuple, Any, Optional
import pandas as pd
import numpy as np
from scipy import stats
from sklearn.ensemble import IsolationForest
from azure.servicebus import ServiceBusClient, ServiceBusMessage
from azure.keyvault.secrets import SecretClient
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
import re

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

    # Quality thresholds
    QUALITY_THRESHOLD = float(os.getenv('QUALITY_THRESHOLD', '95.0'))
    OUTLIER_Z_SCORE_THRESHOLD = float(os.getenv('OUTLIER_Z_SCORE', '3.0'))
    MISSING_VALUE_THRESHOLD = float(os.getenv('MISSING_VALUE_THRESHOLD', '0.05'))

    # Topics
    INPUT_TOPIC = 'data-ingested'
    OUTPUT_TOPIC = 'data-quality-checked'

# ============================================================
# Schema Definitions
# ============================================================

APPLICANT_SCHEMA = {
    'national_id': {
        'type': 'string',
        'required': True,
        'pattern': r'^GHA-\d{9}-\d$',
        'description': 'Ghana Card number'
    },
    'tax_id': {
        'type': 'string',
        'required': False,
        'pattern': r'^TIN\d{10}$',
        'description': 'Tax Identification Number'
    },
    'first_name': {
        'type': 'string',
        'required': True,
        'min_length': 2,
        'max_length': 100
    },
    'last_name': {
        'type': 'string',
        'required': True,
        'min_length': 2,
        'max_length': 100
    },
    'date_of_birth': {
        'type': 'date',
        'required': True,
        'min_age': 18,
        'max_age': 100
    },
    'email': {
        'type': 'email',
        'required': True,
        'pattern': r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    },
    'phone_number': {
        'type': 'string',
        'required': True,
        'pattern': r'^\+233\d{9}$'
    },
    'monthly_income': {
        'type': 'float',
        'required': True,
        'min': 0,
        'max': 10000000
    },
    'monthly_expenses': {
        'type': 'float',
        'required': True,
        'min': 0,
        'max': 10000000
    }
}

BUSINESS_RULES = [
    {
        'name': 'income_greater_than_expenses',
        'condition': lambda data: data.get('monthly_income', 0) > data.get('monthly_expenses', 0),
        'severity': 'warning',
        'message': 'Monthly income should be greater than monthly expenses'
    },
    {
        'name': 'age_verification',
        'condition': lambda data: 18 <= calculate_age(data.get('date_of_birth')) <= 100,
        'severity': 'error',
        'message': 'Age must be between 18 and 100'
    },
    {
        'name': 'requested_amount_reasonable',
        'condition': lambda data: data.get('requested_amount', 0) < (data.get('monthly_income', 0) * 12 * 5),
        'severity': 'warning',
        'message': 'Requested amount should not exceed 5x annual income'
    }
]

# ============================================================
# Helper Functions
// ============================================================

def calculate_age(date_of_birth: str) -> int:
    """Calculate age from date of birth"""
    try:
        dob = pd.to_datetime(date_of_birth)
        today = pd.Timestamp.now()
        age = (today - dob).days // 365
        return age
    except:
        return 0

def validate_email(email: str) -> bool:
    """Validate email format"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))

def validate_ghana_card(national_id: str) -> bool:
    """Validate Ghana Card format"""
    pattern = r'^GHA-\d{9}-\d$'
    return bool(re.match(pattern, national_id))

def validate_phone_number(phone: str) -> bool:
    """Validate Ghana phone number format"""
    pattern = r'^\+233\d{9}$'
    return bool(re.match(pattern, phone))

// ============================================================
# Data Quality Agent Class
# ============================================================

class DataQualityAgent:
    """
    Enterprise-grade data quality validation agent

    Features:
    - Schema validation
    - Business rules validation
    - Outlier detection
    - Missing value analysis
    - Data quality scoring
    - Anomaly detection
    """

    def __init__(self):
        """Initialize the Data Quality Agent"""
        self.config = Config()
        self.credential = DefaultAzureCredential()

        # Initialize clients
        self.service_bus_client = None
        self.blob_service_client = None
        self.secret_client = None

        # Initialize outlier detector
        self.outlier_detector = IsolationForest(
            contamination=0.1,
            random_state=42,
            n_estimators=100
        )

        logger.info("Data Quality Agent initialized")

    def _get_service_bus_client(self) -> ServiceBusClient:
        """Get Service Bus client (lazy initialization)"""
        if not self.service_bus_client:
            conn_string = os.getenv('SERVICE_BUS_CONNECTION_STRING')
            self.service_bus_client = ServiceBusClient.from_connection_string(conn_string)
        return self.service_bus_client

    def validate_schema(self, data: Dict[str, Any], schema: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Validate data against schema

        Args:
            data: Data dictionary to validate
            schema: Schema definition

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []

        for field, rules in schema.items():
            value = data.get(field)

            # Check required fields
            if rules.get('required') and value is None:
                errors.append(f"Missing required field: {field}")
                continue

            if value is None:
                continue

            # Type validation
            field_type = rules.get('type')
            if field_type == 'string' and not isinstance(value, str):
                errors.append(f"Field {field} should be string, got {type(value).__name__}")
            elif field_type == 'float' and not isinstance(value, (int, float)):
                errors.append(f"Field {field} should be numeric, got {type(value).__name__}")

            // Pattern validation
            if 'pattern' in rules and isinstance(value, str):
                if not re.match(rules['pattern'], value):
                    errors.append(f"Field {field} does not match required pattern")

            # Range validation
            if 'min' in rules and isinstance(value, (int, float)):
                if value < rules['min']:
                    errors.append(f"Field {field} is below minimum value {rules['min']}")

            if 'max' in rules and isinstance(value, (int, float)):
                if value > rules['max']:
                    errors.append(f"Field {field} exceeds maximum value {rules['max']}")

            # Length validation
            if 'min_length' in rules and isinstance(value, str):
                if len(value) < rules['min_length']:
                    errors.append(f"Field {field} is too short (min {rules['min_length']})")

            if 'max_length' in rules and isinstance(value, str):
                if len(value) > rules['max_length']:
                    errors.append(f"Field {field} is too long (max {rules['max_length']})")

        return len(errors) == 0, errors

    def validate_business_rules(self, data: Dict[str, Any]) -> Tuple[List[str], List[str]]:
        """
        Validate business rules

        Returns:
            Tuple of (warnings, errors)
        """
        warnings = []
        errors = []

        for rule in BUSINESS_RULES:
            try:
                if not rule['condition'](data):
                    if rule['severity'] == 'error':
                        errors.append(f"{rule['name']}: {rule['message']}")
                    else:
                        warnings.append(f"{rule['name']}: {rule['message']}")
            except Exception as e:
                logger.warning(f"Error evaluating rule {rule['name']}: {str(e)}")

        return warnings, errors

    def detect_outliers(self, data: Dict[str, Any], historical_data: Optional[pd.DataFrame] = None) -> List[str]:
        """
        Detect outliers using statistical methods

        Args:
            data: Current data point
            historical_data: Historical data for comparison

        Returns:
            List of outlier warnings
        """
        outliers = []

        # Numeric fields to check
        numeric_fields = ['monthly_income', 'monthly_expenses', 'requested_amount']

        for field in numeric_fields:
            value = data.get(field)
            if value is None:
                continue

            # Z-score method (if historical data available)
            if historical_data is not None and field in historical_data.columns:
                mean = historical_data[field].mean()
                std = historical_data[field].std()

                if std > 0:
                    z_score = abs((value - mean) / std)
                    if z_score > self.config.OUTLIER_Z_SCORE_THRESHOLD:
                        outliers.append(f"{field} is an outlier (z-score: {z_score:.2f})")

            // Simple range checks (fallback)
            else:
                if field == 'monthly_income' and value > 1000000:
                    outliers.append(f"{field} is unusually high: {value}")
                elif field == 'monthly_expenses' and value > 500000:
                    outliers.append(f"{field} is unusually high: {value}")

        return outliers

    def calculate_quality_score(self,
                                schema_valid: bool,
                                schema_errors: List[str],
                                business_warnings: List[str],
                                business_errors: List[str],
                                outliers: List[str],
                                missing_fields: List[str]) -> float:
        """
        Calculate overall data quality score (0-100)

        Scoring:
        - Schema validation: 40 points
        - Business rules: 30 points
        - Outlier detection: 20 points
        - Completeness: 10 points
        """
        score = 100.0

        # Schema validation (40 points)
        if not schema_valid:
            score -= 40 * (len(schema_errors) / max(len(APPLICANT_SCHEMA), 1))

        # Business rules (30 points)
        if business_errors:
            score -= 30
        elif business_warnings:
            score -= 10 * (len(business_warnings) / max(len(BUSINESS_RULES), 1))

        # Outliers (20 points)
        if outliers:
            score -= min(20, 5 * len(outliers))

        // Completeness (10 points)
        if missing_fields:
            score -= 10 * (len(missing_fields) / max(len(APPLICANT_SCHEMA), 1))

        return max(0.0, score)

    def process_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main data quality processing function

        Args:
            data: Input data dictionary

        Returns:
            Quality report dictionary
        """
        logger.info(f"Processing data for record_id: {data.get('record_id', 'unknown')}")

        # 1. Schema validation
        schema_valid, schema_errors = self.validate_schema(data, APPLICANT_SCHEMA)

        // 2. Business rules validation
        business_warnings, business_errors = self.validate_business_rules(data)

        # 3. Outlier detection
        outliers = self.detect_outliers(data)

        // 4. Missing fields analysis
        missing_fields = [
            field for field, rules in APPLICANT_SCHEMA.items()
            if rules.get('required') and data.get(field) is None
        ]

        # 5. Calculate quality score
        quality_score = self.calculate_quality_score(
            schema_valid, schema_errors, business_warnings,
            business_errors, outliers, missing_fields
        )

        // Determine recommendation
        if quality_score >= self.config.QUALITY_THRESHOLD:
            recommendation = 'ACCEPT'
        elif quality_score >= 70:
            recommendation = 'REVIEW'
        else:
            recommendation = 'REJECT'

        # Build quality report
        quality_report = {
            'record_id': data.get('record_id'),
            'timestamp': datetime.utcnow().isoformat(),
            'quality_score': round(quality_score, 2),
            'recommendation': recommendation,
            'schema_valid': schema_valid,
            'schema_errors': schema_errors,
            'business_warnings': business_warnings,
            'business_errors': business_errors,
            'outliers': outliers,
            'missing_fields': missing_fields,
            'processed_data': data if recommendation == 'ACCEPT' else None
        }

        logger.info(f"Quality score: {quality_score:.2f}, Recommendation: {recommendation}")

        return quality_report

    def publish_to_service_bus(self, message: Dict[str, Any], topic_name: str):
        """
        Publish message to Service Bus topic

        Args:
            message: Message dictionary
            topic_name: Topic name
        """
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
    topic_name="data-ingested",
    subscription_name="data-quality-agent-sub",
    connection="SERVICE_BUS_CONNECTION_STRING"
)
def data_quality_agent_trigger(message: func.ServiceBusMessage):
    """
    Azure Function triggered by Service Bus message

    Args:
        message: Service Bus message from 'data-ingested' topic
    """
    try:
        # Parse message
        message_body = message.get_body().decode('utf-8')
        data = json.loads(message_body)

        logger.info(f"Received message: {message.message_id}")

        # Initialize agent
        agent = DataQualityAgent()

        # Process data
        quality_report = agent.process_data(data)

        # Publish to next topic if quality is acceptable
        if quality_report['recommendation'] in ['ACCEPT', 'REVIEW']:
            agent.publish_to_service_bus(
                {
                    'record_id': quality_report['record_id'],
                    'quality_score': quality_report['quality_score'],
                    'data': quality_report['processed_data'],
                    'warnings': quality_report['business_warnings'],
                    'outliers': quality_report['outliers']
                },
                Config.OUTPUT_TOPIC
            )
            logger.info(f"Message processed successfully: {message.message_id}")
        else:
            logger.warning(f"Message rejected due to low quality: {quality_report['quality_score']}")

        # Store quality report for audit
        # TODO: Store in PostgreSQL audit_logs table

    except Exception as e:
        logger.error(f"Error processing message: {str(e)}", exc_info=True)
        raise

@app.timer_trigger(
    arg_name="timer",
    schedule="0 0 2 * * *",  # Daily at 2 AM UTC
    run_on_startup=False
)
def data_quality_metrics_aggregation(timer: func.TimerRequest):
    """
    Scheduled function to aggregate data quality metrics

    Runs daily to calculate:
    - Average quality scores
    - Common error patterns
    - Outlier trends
    """
    logger.info("Running daily data quality metrics aggregation")

    # TODO: Implement metrics aggregation
    # - Query quality reports from last 24 hours
    # - Calculate aggregate metrics
    // - Publish to monitoring dashboard
    # - Alert if quality degrades

    logger.info("Metrics aggregation completed")
