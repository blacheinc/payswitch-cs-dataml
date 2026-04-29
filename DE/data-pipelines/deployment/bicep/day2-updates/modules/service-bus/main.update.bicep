@description('Existing Service Bus namespace name')
param serviceBusNamespaceName string

resource serviceBusNamespace 'Microsoft.ServiceBus/namespaces@2022-10-01-preview' existing = {
  name: serviceBusNamespaceName
}

resource dataAwaitsIngestionTopic 'Microsoft.ServiceBus/namespaces/topics@2022-10-01-preview' existing = {
  parent: serviceBusNamespace
  name: 'data-awaits-ingestion'
}

resource dataAwaitsIngestionAdfTriggerSub 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2022-10-01-preview' existing = {
  parent: dataAwaitsIngestionTopic
  name: 'adf-trigger-subscription'
}

resource dataAwaitsIngestionTempPeekSub 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2022-10-01-preview' existing = {
  parent: dataAwaitsIngestionTopic
  name: 'temp-peek-subscription'
}

resource dataIngestedTopic 'Microsoft.ServiceBus/namespaces/topics@2022-10-01-preview' existing = {
  parent: serviceBusNamespace
  name: 'data-ingested'
}

resource dataIngestedQualityReportSub 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2022-10-01-preview' = {
  parent: dataIngestedTopic
  name: 'quality_report'
  properties: {
    lockDuration: 'PT5M'
    requiresSession: false
    defaultMessageTimeToLive: 'P1D'
    deadLetteringOnMessageExpiration: true
    deadLetteringOnFilterEvaluationExceptions: true
    maxDeliveryCount: 10
    enableBatchedOperations: true
  }
}

resource dataIngestedStartTransformationSub 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2022-10-01-preview' = {
  parent: dataIngestedTopic
  name: 'start-transformation'
  properties: {
    lockDuration: 'PT5M'
    requiresSession: false
    defaultMessageTimeToLive: 'P1D'
    deadLetteringOnMessageExpiration: true
    deadLetteringOnFilterEvaluationExceptions: true
    maxDeliveryCount: 10
    enableBatchedOperations: true
  }
}

resource dataIngestedTransformedSub 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2022-10-01-preview' = {
  parent: dataIngestedTopic
  name: 'transformed'
  properties: {
    lockDuration: 'PT5M'
    requiresSession: false
    defaultMessageTimeToLive: 'P1D'
    deadLetteringOnMessageExpiration: true
    deadLetteringOnFilterEvaluationExceptions: true
    maxDeliveryCount: 10
    enableBatchedOperations: true
  }
}

resource schemaMappingTopic 'Microsoft.ServiceBus/namespaces/topics@2022-10-01-preview' existing = {
  parent: serviceBusNamespace
  name: 'schema-mapping-service'
}

resource transformationServiceTopic 'Microsoft.ServiceBus/namespaces/topics@2022-10-01-preview' = {
  parent: serviceBusNamespace
  name: 'transformation-service'
  properties: {
    maxSizeInMegabytes: 1024
    defaultMessageTimeToLive: 'P7D'
    requiresDuplicateDetection: true
    duplicateDetectionHistoryTimeWindow: 'PT10M'
    enableBatchedOperations: true
    enablePartitioning: false
    supportOrdering: true
  }
}

resource transformStartedSub 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2022-10-01-preview' = {
  parent: transformationServiceTopic
  name: 'transform-started'
  properties: {
    lockDuration: 'PT5M'
    requiresSession: false
    defaultMessageTimeToLive: 'P1D'
    deadLetteringOnMessageExpiration: true
    deadLetteringOnFilterEvaluationExceptions: true
    maxDeliveryCount: 10
    enableBatchedOperations: true
  }
}

resource trainingCurationCompleteSub 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2022-10-01-preview' = {
  parent: transformationServiceTopic
  name: 'training-curation-complete'
  properties: {
    lockDuration: 'PT5M'
    requiresSession: false
    defaultMessageTimeToLive: 'P1D'
    deadLetteringOnMessageExpiration: true
    deadLetteringOnFilterEvaluationExceptions: true
    maxDeliveryCount: 10
    enableBatchedOperations: true
  }
}

resource trainingReadyForMlSub 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2022-10-01-preview' = {
  parent: transformationServiceTopic
  name: 'training-ready-for-ml'
  properties: {
    lockDuration: 'PT5M'
    requiresSession: false
    defaultMessageTimeToLive: 'P1D'
    deadLetteringOnMessageExpiration: true
    deadLetteringOnFilterEvaluationExceptions: true
    maxDeliveryCount: 10
    enableBatchedOperations: true
  }
}

resource inferenceFeaturesReadySub 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2022-10-01-preview' = {
  parent: transformationServiceTopic
  name: 'inference-features-ready'
  properties: {
    lockDuration: 'PT5M'
    requiresSession: false
    defaultMessageTimeToLive: 'P1D'
    deadLetteringOnMessageExpiration: true
    deadLetteringOnFilterEvaluationExceptions: true
    maxDeliveryCount: 10
    enableBatchedOperations: true
  }
}

resource inferenceHardStopSub 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2022-10-01-preview' = {
  parent: transformationServiceTopic
  name: 'inference-hard-stop'
  properties: {
    lockDuration: 'PT5M'
    requiresSession: false
    defaultMessageTimeToLive: 'P1D'
    deadLetteringOnMessageExpiration: true
    deadLetteringOnFilterEvaluationExceptions: true
    maxDeliveryCount: 10
    enableBatchedOperations: true
  }
}

resource transformationFailedSub 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2022-10-01-preview' = {
  parent: transformationServiceTopic
  name: 'failed'
  properties: {
    lockDuration: 'PT5M'
    requiresSession: false
    defaultMessageTimeToLive: 'P1D'
    deadLetteringOnMessageExpiration: true
    deadLetteringOnFilterEvaluationExceptions: true
    maxDeliveryCount: 10
    enableBatchedOperations: true
  }
}

resource schemaAnalysisCompleteSub 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2022-10-01-preview' existing = {
  parent: schemaMappingTopic
  name: 'analysis-complete'
}

resource schemaAnonymizationCompleteSub 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2022-10-01-preview' existing = {
  parent: schemaMappingTopic
  name: 'anonymization-complete'
}

resource schemaFailedSub 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2022-10-01-preview' existing = {
  parent: schemaMappingTopic
  name: 'failed'
}

resource schemaIntrospectionCompleteSub 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2022-10-01-preview' existing = {
  parent: schemaMappingTopic
  name: 'introspection-complete'
}

resource schemaMappingCompleteSub 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2022-10-01-preview' existing = {
  parent: schemaMappingTopic
  name: 'mapping-complete'
}

resource schemaSamplingCompleteSub 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2022-10-01-preview' existing = {
  parent: schemaMappingTopic
  name: 'sampling-complete'
}

resource schemaDetectedSub 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2022-10-01-preview' existing = {
  parent: schemaMappingTopic
  name: 'schema-detected'
}

// Replace each subscription's default allow-all rule with a deny-all baseline.
resource adfTriggerDefaultRule 'Microsoft.ServiceBus/namespaces/topics/subscriptions/rules@2022-10-01-preview' = {
  parent: dataAwaitsIngestionAdfTriggerSub
  name: '$Default'
  properties: {
    filterType: 'SqlFilter'
    sqlFilter: {
      sqlExpression: '1 = 0'
    }
  }
}

resource tempPeekDefaultRule 'Microsoft.ServiceBus/namespaces/topics/subscriptions/rules@2022-10-01-preview' = {
  parent: dataAwaitsIngestionTempPeekSub
  name: '$Default'
  properties: {
    filterType: 'SqlFilter'
    sqlFilter: {
      sqlExpression: '1 = 0'
    }
  }
}

resource qualityReportDefaultRule 'Microsoft.ServiceBus/namespaces/topics/subscriptions/rules@2022-10-01-preview' = {
  parent: dataIngestedQualityReportSub
  name: '$Default'
  properties: {
    filterType: 'SqlFilter'
    sqlFilter: {
      sqlExpression: '1 = 0'
    }
  }
}

resource startTransformationDefaultRule 'Microsoft.ServiceBus/namespaces/topics/subscriptions/rules@2022-10-01-preview' = {
  parent: dataIngestedStartTransformationSub
  name: '$Default'
  properties: {
    filterType: 'SqlFilter'
    sqlFilter: {
      sqlExpression: '1 = 0'
    }
  }
}

resource transformedDefaultRule 'Microsoft.ServiceBus/namespaces/topics/subscriptions/rules@2022-10-01-preview' = {
  parent: dataIngestedTransformedSub
  name: '$Default'
  properties: {
    filterType: 'SqlFilter'
    sqlFilter: {
      sqlExpression: '1 = 0'
    }
  }
}

resource analysisDefaultRule 'Microsoft.ServiceBus/namespaces/topics/subscriptions/rules@2022-10-01-preview' = {
  parent: schemaAnalysisCompleteSub
  name: '$Default'
  properties: {
    filterType: 'SqlFilter'
    sqlFilter: {
      sqlExpression: '1 = 0'
    }
  }
}

resource anonymizationDefaultRule 'Microsoft.ServiceBus/namespaces/topics/subscriptions/rules@2022-10-01-preview' = {
  parent: schemaAnonymizationCompleteSub
  name: '$Default'
  properties: {
    filterType: 'SqlFilter'
    sqlFilter: {
      sqlExpression: '1 = 0'
    }
  }
}

resource failedDefaultRule 'Microsoft.ServiceBus/namespaces/topics/subscriptions/rules@2022-10-01-preview' = {
  parent: schemaFailedSub
  name: '$Default'
  properties: {
    filterType: 'SqlFilter'
    sqlFilter: {
      sqlExpression: '1 = 0'
    }
  }
}

resource introspectionDefaultRule 'Microsoft.ServiceBus/namespaces/topics/subscriptions/rules@2022-10-01-preview' = {
  parent: schemaIntrospectionCompleteSub
  name: '$Default'
  properties: {
    filterType: 'SqlFilter'
    sqlFilter: {
      sqlExpression: '1 = 0'
    }
  }
}

resource mappingDefaultRule 'Microsoft.ServiceBus/namespaces/topics/subscriptions/rules@2022-10-01-preview' = {
  parent: schemaMappingCompleteSub
  name: '$Default'
  properties: {
    filterType: 'SqlFilter'
    sqlFilter: {
      sqlExpression: '1 = 0'
    }
  }
}

resource samplingDefaultRule 'Microsoft.ServiceBus/namespaces/topics/subscriptions/rules@2022-10-01-preview' = {
  parent: schemaSamplingCompleteSub
  name: '$Default'
  properties: {
    filterType: 'SqlFilter'
    sqlFilter: {
      sqlExpression: '1 = 0'
    }
  }
}

resource schemaDetectedDefaultRule 'Microsoft.ServiceBus/namespaces/topics/subscriptions/rules@2022-10-01-preview' = {
  parent: schemaDetectedSub
  name: '$Default'
  properties: {
    filterType: 'SqlFilter'
    sqlFilter: {
      sqlExpression: '1 = 0'
    }
  }
}

resource transformStartedDefaultRule 'Microsoft.ServiceBus/namespaces/topics/subscriptions/rules@2022-10-01-preview' = {
  parent: transformStartedSub
  name: '$Default'
  properties: {
    filterType: 'SqlFilter'
    sqlFilter: {
      sqlExpression: '1 = 0'
    }
  }
}

resource trainingCurationCompleteDefaultRule 'Microsoft.ServiceBus/namespaces/topics/subscriptions/rules@2022-10-01-preview' = {
  parent: trainingCurationCompleteSub
  name: '$Default'
  properties: {
    filterType: 'SqlFilter'
    sqlFilter: {
      sqlExpression: '1 = 0'
    }
  }
}

resource trainingReadyForMlDefaultRule 'Microsoft.ServiceBus/namespaces/topics/subscriptions/rules@2022-10-01-preview' = {
  parent: trainingReadyForMlSub
  name: '$Default'
  properties: {
    filterType: 'SqlFilter'
    sqlFilter: {
      sqlExpression: '1 = 0'
    }
  }
}

resource inferenceFeaturesReadyDefaultRule 'Microsoft.ServiceBus/namespaces/topics/subscriptions/rules@2022-10-01-preview' = {
  parent: inferenceFeaturesReadySub
  name: '$Default'
  properties: {
    filterType: 'SqlFilter'
    sqlFilter: {
      sqlExpression: '1 = 0'
    }
  }
}

resource inferenceHardStopDefaultRule 'Microsoft.ServiceBus/namespaces/topics/subscriptions/rules@2022-10-01-preview' = {
  parent: inferenceHardStopSub
  name: '$Default'
  properties: {
    filterType: 'SqlFilter'
    sqlFilter: {
      sqlExpression: '1 = 0'
    }
  }
}

resource transformationFailedDefaultRule 'Microsoft.ServiceBus/namespaces/topics/subscriptions/rules@2022-10-01-preview' = {
  parent: transformationFailedSub
  name: '$Default'
  properties: {
    filterType: 'SqlFilter'
    sqlFilter: {
      sqlExpression: '1 = 0'
    }
  }
}

resource adfProcessingSystemFilter 'Microsoft.ServiceBus/namespaces/topics/subscriptions/rules@2022-10-01-preview' = {
  parent: dataAwaitsIngestionAdfTriggerSub
  name: 'ADFProcessingSystemFilter'
  properties: {
    filterType: 'SqlFilter'
    sqlFilter: {
      sqlExpression: '''
processing_system = 'ADF'
'''
    }
  }
}

resource checkTrainingUploadIdRule 'Microsoft.ServiceBus/namespaces/topics/subscriptions/rules@2022-10-01-preview' = {
  parent: dataAwaitsIngestionTempPeekSub
  name: 'CheckTrainingUploadID'
  properties: {
    filterType: 'SqlFilter'
    sqlFilter: {
      sqlExpression: '''
processing_system = 'ADF'
'''
    }
  }
}

resource qualityReportFilterRule 'Microsoft.ServiceBus/namespaces/topics/subscriptions/rules@2022-10-01-preview' = {
  parent: dataIngestedQualityReportSub
  name: 'quality_report_filter'
  properties: {
    filterType: 'SqlFilter'
    sqlFilter: {
      sqlExpression: '''
run_id IS NOT NULL AND subscription = 'quality_report'
'''
    }
  }
}

resource runIdCheckRule 'Microsoft.ServiceBus/namespaces/topics/subscriptions/rules@2022-10-01-preview' = {
  parent: dataIngestedStartTransformationSub
  name: 'RunIDCheck'
  properties: {
    filterType: 'SqlFilter'
    sqlFilter: {
      sqlExpression: '''
subscription = 'start-transformation'
AND run_id IS NOT NULL
AND training_upload_id IS NOT NULL
AND bank_id IS NOT NULL
AND bronze_blob_path IS NOT NULL
AND (status IS NULL OR status <> 'ERROR')
'''
    }
  }
}

resource transformedFilterRule 'Microsoft.ServiceBus/namespaces/topics/subscriptions/rules@2022-10-01-preview' = {
  parent: dataIngestedTransformedSub
  name: 'transformed_filter'
  properties: {
    filterType: 'SqlFilter'
    sqlFilter: {
      sqlExpression: '''
subscription = 'transformed'
AND status = 'TRANSFORMED'
AND run_id IS NOT NULL
AND transformed_file_path IS NOT NULL
'''
    }
  }
}

resource analysisFilterRule 'Microsoft.ServiceBus/namespaces/topics/subscriptions/rules@2022-10-01-preview' = {
  parent: schemaAnalysisCompleteSub
  name: 'analysis_filter'
  properties: {
    filterType: 'SqlFilter'
    sqlFilter: {
      sqlExpression: '''
run_id IS NOT NULL AND training_upload_id IS NOT NULL AND subscription = 'analysis-complete'
'''
    }
  }
}

resource anonymizationFilterRule 'Microsoft.ServiceBus/namespaces/topics/subscriptions/rules@2022-10-01-preview' = {
  parent: schemaAnonymizationCompleteSub
  name: 'anonymization_filter'
  properties: {
    filterType: 'SqlFilter'
    sqlFilter: {
      sqlExpression: '''
run_id IS NOT NULL AND training_upload_id IS NOT NULL AND subscription = 'anonymization-complete'
'''
    }
  }
}

resource failedFilterRule 'Microsoft.ServiceBus/namespaces/topics/subscriptions/rules@2022-10-01-preview' = {
  parent: schemaFailedSub
  name: 'failed_filter'
  properties: {
    filterType: 'SqlFilter'
    sqlFilter: {
      sqlExpression: '''
run_id IS NOT NULL AND subscription = 'failed'
'''
    }
  }
}

resource introspectionFilterRule 'Microsoft.ServiceBus/namespaces/topics/subscriptions/rules@2022-10-01-preview' = {
  parent: schemaIntrospectionCompleteSub
  name: 'introspection_filter'
  properties: {
    filterType: 'SqlFilter'
    sqlFilter: {
      sqlExpression: '''
run_id IS NOT NULL AND training_upload_id IS NOT NULL AND subscription = 'introspection-complete'
'''
    }
  }
}

resource mappingCompleteFilterRule 'Microsoft.ServiceBus/namespaces/topics/subscriptions/rules@2022-10-01-preview' = {
  parent: schemaMappingCompleteSub
  name: 'mapping_complete_filter'
  properties: {
    filterType: 'SqlFilter'
    sqlFilter: {
      sqlExpression: '''
status = 'MAPPING_COMPLETE' AND subscription = 'mapping-complete'
'''
    }
  }
}

resource samplingFilterRule 'Microsoft.ServiceBus/namespaces/topics/subscriptions/rules@2022-10-01-preview' = {
  parent: schemaSamplingCompleteSub
  name: 'sampling_filter'
  properties: {
    filterType: 'SqlFilter'
    sqlFilter: {
      sqlExpression: '''
run_id IS NOT NULL AND training_upload_id IS NOT NULL AND subscription = 'sampling-complete'
'''
    }
  }
}

resource schemaDetectedFilterRule 'Microsoft.ServiceBus/namespaces/topics/subscriptions/rules@2022-10-01-preview' = {
  parent: schemaDetectedSub
  name: 'schema_detected_filter'
  properties: {
    filterType: 'SqlFilter'
    sqlFilter: {
      sqlExpression: '''
run_id IS NOT NULL AND training_upload_id IS NOT NULL AND subscription = 'schema-detected'
'''
    }
  }
}

resource transformStartedFilterRule 'Microsoft.ServiceBus/namespaces/topics/subscriptions/rules@2022-10-01-preview' = {
  parent: transformStartedSub
  name: 'transform_started_filter'
  properties: {
    filterType: 'SqlFilter'
    sqlFilter: {
      sqlExpression: '''
status = 'STARTING' AND subscription = 'transform-started'
'''
    }
  }
}

resource trainingCurationCompleteFilterRule 'Microsoft.ServiceBus/namespaces/topics/subscriptions/rules@2022-10-01-preview' = {
  parent: trainingCurationCompleteSub
  name: 'training_curation_complete_filter'
  properties: {
    filterType: 'SqlFilter'
    sqlFilter: {
      sqlExpression: '''
flow_type = 'training' AND status = 'TRANSFORMED' AND subscription = 'training-curation-complete'
'''
    }
  }
}

resource trainingReadyForMlFilterRule 'Microsoft.ServiceBus/namespaces/topics/subscriptions/rules@2022-10-01-preview' = {
  parent: trainingReadyForMlSub
  name: 'training_ready_for_ml_filter'
  properties: {
    filterType: 'SqlFilter'
    sqlFilter: {
      sqlExpression: '''
flow_type = 'training' AND status = 'ML_HANDOFF_READY' AND subscription = 'training-ready-for-ml'
'''
    }
  }
}

resource inferenceFeaturesReadyFilterRule 'Microsoft.ServiceBus/namespaces/topics/subscriptions/rules@2022-10-01-preview' = {
  parent: inferenceFeaturesReadySub
  name: 'inference_features_ready_filter'
  properties: {
    filterType: 'SqlFilter'
    sqlFilter: {
      sqlExpression: '''
flow_type = 'inference' AND status = 'INFERENCE_REQUEST_READY' AND subscription = 'inference-features-ready'
'''
    }
  }
}

resource inferenceHardStopFilterRule 'Microsoft.ServiceBus/namespaces/topics/subscriptions/rules@2022-10-01-preview' = {
  parent: inferenceHardStopSub
  name: 'inference_hard_stop_filter'
  properties: {
    filterType: 'SqlFilter'
    sqlFilter: {
      sqlExpression: '''
flow_type = 'inference' AND status = 'HARD_STOP' AND subscription = 'inference-hard-stop'
'''
    }
  }
}

resource transformationFailedFilterRule 'Microsoft.ServiceBus/namespaces/topics/subscriptions/rules@2022-10-01-preview' = {
  parent: transformationFailedSub
  name: 'transformation_failed_filter'
  properties: {
    filterType: 'SqlFilter'
    sqlFilter: {
      sqlExpression: '''
status = 'FAILED' AND subscription = 'failed'
'''
    }
  }
}

output updatedRuleNames array = [
  adfProcessingSystemFilter.name
  checkTrainingUploadIdRule.name
  qualityReportFilterRule.name
  runIdCheckRule.name
  transformedFilterRule.name
  analysisFilterRule.name
  anonymizationFilterRule.name
  failedFilterRule.name
  introspectionFilterRule.name
  mappingCompleteFilterRule.name
  samplingFilterRule.name
  schemaDetectedFilterRule.name
  transformStartedFilterRule.name
  trainingCurationCompleteFilterRule.name
  trainingReadyForMlFilterRule.name
  inferenceFeaturesReadyFilterRule.name
  inferenceHardStopFilterRule.name
  transformationFailedFilterRule.name
]
