# Quarterly Disaster Recovery Drill Procedures
## Credit Scoring & Decisioning Engine

**Document Version:** 1.0
**Last Updated:** 2025-11-12
**Maintained By:** Blache Ltd Infrastructure Team

---

## 📋 Overview

This document outlines the quarterly disaster recovery (DR) drill procedures for the PaySwitch Credit Scoring platform. Regular DR drills ensure that recovery procedures are tested, documented, and understood by the team.

### Objectives

1. **Validate Recovery Procedures:** Ensure documented procedures work as expected
2. **Test Recovery Time:** Measure actual RTO (Recovery Time Objective) vs. target
3. **Verify Data Integrity:** Confirm data restoration is complete and accurate
4. **Train Team:** Ensure team members understand their roles during incidents
5. **Update Documentation:** Improve procedures based on lessons learned

### DR Targets

| Metric | Target | Current |
|--------|--------|---------|
| **RTO** (Recovery Time Objective) | 4 hours | TBD (validate in drill) |
| **RPO** (Recovery Point Objective) | 15 minutes | 4 hours (backup frequency) |
| **Data Loss** | <0.01% | TBD (validate in drill) |
| **Service Availability** | 99.9% | TBD (measure monthly) |

---

## 📅 DR Drill Schedule

### Quarterly Schedule (2025)

| Quarter | Month | Drill Type | Focus Area | Participants |
|---------|-------|------------|------------|--------------|
| **Q1** | January | Database Failover | PostgreSQL geo-redundant recovery | Infrastructure + DBA |
| **Q2** | April | Full Region Failover | Multi-service recovery | All teams |
| **Q3** | July | Data Corruption Recovery | Point-in-time restore | Infrastructure + Data |
| **Q4** | October | Complete System DR | End-to-end recovery | All teams + Management |

### Annual Review (December)

- Review all quarterly drill results
- Update DR procedures based on learnings
- Update RTO/RPO targets
- Present to executive management

---

## 🎯 Drill #1: Database Failover (Q1)

**Scenario:** Primary PostgreSQL database failure in West Europe region

**Duration:** 3-4 hours
**Participants:** Infrastructure team, Database Administrator, DevOps
**Prerequisites:** Valid geo-redundant backups, staging environment available

### Pre-Drill Preparation (Week Before)

**1. Review Current Configuration**
```bash
# Verify geo-redundant backup is enabled
az postgres flexible-server show \
  --resource-group payswitch-creditscore-prod-data-rg \
  --name $(az postgres flexible-server list --query "[0].name" -o tsv) \
  --query "backup.geoRedundantBackup"

# Expected output: "Enabled"
```

**2. Document Current State**
```bash
# Export database metrics
az monitor metrics list \
  --resource <postgres-resource-id> \
  --metric "storage_percent,cpu_percent,memory_percent" \
  --start-time $(date -u -d "1 hour ago" +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --interval PT1M \
  --output table > pre-drill-metrics.txt
```

**3. Notify Stakeholders**
- Send email to all participants (1 week before)
- Schedule 30-minute kick-off meeting (day before)
- Confirm access to required systems

**4. Create Test Checklist**
- [ ] Staging environment prepared
- [ ] Backup verified (within last 24 hours)
- [ ] Communication channels ready (Slack, Teams)
- [ ] Monitoring dashboards configured
- [ ] Runbook printed and available

### Drill Execution (Day Of)

#### Phase 1: Baseline Documentation (30 minutes)

**Start Time:** __:__
**End Time:** __:__

**1. Document Current Database State**
```sql
-- Connect to production database (read-only)
psql "host=<prod-postgres-fqdn> dbname=credit_scoring user=csadmin sslmode=require"

-- Record database size
SELECT
  pg_database.datname,
  pg_size_pretty(pg_database_size(pg_database.datname)) AS size
FROM pg_database
ORDER BY pg_database_size(pg_database.datname) DESC;

-- Record table row counts
SELECT
  schemaname,
  tablename,
  n_live_tup AS row_count
FROM pg_stat_user_tables
ORDER BY n_live_tup DESC;

-- Save output to file: baseline-db-state.txt
```

**2. Document Application State**
```bash
# Check application health
kubectl get pods -n credit-scoring-prod
kubectl top nodes
kubectl top pods -n credit-scoring-prod

# Save output to file: baseline-app-state.txt
```

**3. Record Test Transaction**
```sql
-- Insert test record with known timestamp
INSERT INTO credit_scoring.dr_test_records (
  test_id,
  drill_date,
  drill_type,
  test_data
) VALUES (
  gen_random_uuid(),
  NOW(),
  'Q1-2025-Database-Failover',
  '{"test": "baseline record for DR drill"}'
);

-- Record the test_id for later verification
SELECT * FROM credit_scoring.dr_test_records
WHERE drill_type = 'Q1-2025-Database-Failover'
ORDER BY drill_date DESC LIMIT 1;

-- Save test_id: _______________________________
```

#### Phase 2: Simulate Database Failure (15 minutes)

**Start Time:** __:__
**End Time:** __:__

**1. Trigger Failure in Staging (DO NOT DO THIS IN PROD)**
```bash
# In staging environment only
az postgres flexible-server stop \
  --resource-group payswitch-creditscore-staging-data-rg \
  --name $(az postgres flexible-server list \
    --resource-group payswitch-creditscore-staging-data-rg \
    --query "[0].name" -o tsv)
```

**2. Verify Application Impact**
```bash
# Check application logs for database errors
kubectl logs -n credit-scoring-staging \
  -l app=credit-api \
  --tail=100 \
  --since=5m

# Expected: Connection errors, retry attempts
```

**3. Trigger Alerts**
```bash
# Verify monitoring alerts fired
az monitor activity-log list \
  --resource-group payswitch-creditscore-staging-data-rg \
  --offset 10m \
  --output table
```

#### Phase 3: Restore from Geo-Redundant Backup (90-120 minutes)

**Start Time:** __:__
**End Time:** __:__

**1. Identify Latest Backup**
```bash
# List available backups
az postgres flexible-server backup list \
  --resource-group payswitch-creditscore-staging-data-rg \
  --server-name <staging-postgres-server> \
  --output table

# Record latest backup time: _______________________________
```

**2. Perform Geo-Restore to New Server**
```bash
# Restore database to new server in paired region (North Europe)
az postgres flexible-server geo-restore \
  --resource-group payswitch-creditscore-staging-dr-rg \
  --name payswitch-creditscore-staging-postgres-dr \
  --source-server <source-server-resource-id> \
  --location northeurope

# This operation takes 60-90 minutes for typical database sizes
# Monitor progress:
az postgres flexible-server show \
  --resource-group payswitch-creditscore-staging-dr-rg \
  --name payswitch-creditscore-staging-postgres-dr \
  --query "state" \
  --output tsv

# Expected states: "Creating" → "Updating" → "Ready"
```

**3. Monitor Restore Progress**
```bash
# Create monitoring script
cat > monitor-restore.sh <<'EOF'
#!/bin/bash
while true; do
  STATE=$(az postgres flexible-server show \
    --resource-group payswitch-creditscore-staging-dr-rg \
    --name payswitch-creditscore-staging-postgres-dr \
    --query "state" -o tsv)

  echo "$(date): Database state: $STATE"

  if [ "$STATE" == "Ready" ]; then
    echo "Restore complete!"
    break
  fi

  sleep 60
done
EOF

chmod +x monitor-restore.sh
./monitor-restore.sh
```

#### Phase 4: Validate Restored Database (30 minutes)

**Start Time:** __:__
**End Time:** __:__

**1. Connect to Restored Database**
```bash
# Get new connection string
az postgres flexible-server show \
  --resource-group payswitch-creditscore-staging-dr-rg \
  --name payswitch-creditscore-staging-postgres-dr \
  --query "fullyQualifiedDomainName" -o tsv

# Connection string: _______________________________
```

**2. Verify Database Integrity**
```sql
-- Connect to restored database
psql "host=<dr-postgres-fqdn> dbname=credit_scoring user=csadmin sslmode=require"

-- Verify database size matches baseline
SELECT
  pg_database.datname,
  pg_size_pretty(pg_database_size(pg_database.datname)) AS size
FROM pg_database
ORDER BY pg_database_size(pg_database.datname) DESC;

-- Verify table row counts match baseline (±1%)
SELECT
  schemaname,
  tablename,
  n_live_tup AS row_count
FROM pg_stat_user_tables
ORDER BY n_live_tup DESC;

-- Verify test record exists
SELECT * FROM credit_scoring.dr_test_records
WHERE drill_type = 'Q1-2025-Database-Failover'
ORDER BY drill_date DESC LIMIT 1;

-- Test record found: YES / NO
-- Data matches: YES / NO
```

**3. Run Data Integrity Checks**
```sql
-- Check for corruption
SELECT
  schemaname,
  tablename,
  pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;

-- Verify referential integrity
DO $$
DECLARE
  r RECORD;
BEGIN
  FOR r IN (
    SELECT conrelid::regclass AS table_name,
           conname AS constraint_name
    FROM pg_constraint
    WHERE contype = 'f'
  ) LOOP
    BEGIN
      EXECUTE format('SET check_function_bodies = false; ALTER TABLE %s VALIDATE CONSTRAINT %s;',
                     r.table_name, r.constraint_name);
      RAISE NOTICE 'Constraint % on % is valid', r.constraint_name, r.table_name;
    EXCEPTION WHEN OTHERS THEN
      RAISE WARNING 'Constraint % on % FAILED: %', r.constraint_name, r.table_name, SQLERRM;
    END;
  END LOOP;
END $$;

-- All constraints valid: YES / NO
```

#### Phase 5: Reconfigure Application (45 minutes)

**Start Time:** __:__
**End Time:** __:__

**1. Update Connection Strings**
```bash
# Update Key Vault secret with new connection string
az keyvault secret set \
  --vault-name <keyvault-name> \
  --name "PostgreSQL-ConnectionString-DR" \
  --value "Server=<dr-postgres-fqdn>;Database=credit_scoring;Port=5432;User Id=csadmin;Password=***;Ssl Mode=Require;"

# Verify secret update
az keyvault secret show \
  --vault-name <keyvault-name> \
  --name "PostgreSQL-ConnectionString-DR" \
  --query "value" -o tsv
```

**2. Update Application Configuration**
```bash
# Update Kubernetes secret
kubectl create secret generic postgres-connection-dr \
  --from-literal=connection-string="$(az keyvault secret show \
    --vault-name <keyvault-name> \
    --name PostgreSQL-ConnectionString-DR \
    --query value -o tsv)" \
  --namespace credit-scoring-staging \
  --dry-run=client -o yaml | kubectl apply -f -

# Restart pods to pick up new configuration
kubectl rollout restart deployment/credit-api -n credit-scoring-staging
kubectl rollout restart deployment/feature-service -n credit-scoring-staging

# Wait for rollout to complete
kubectl rollout status deployment/credit-api -n credit-scoring-staging
```

**3. Verify Application Connectivity**
```bash
# Check pod logs for successful database connection
kubectl logs -n credit-scoring-staging \
  -l app=credit-api \
  --tail=50 \
  | grep -i "database\|connection\|postgres"

# Expected: Successful connection messages, no errors
```

#### Phase 6: End-to-End Testing (30 minutes)

**Start Time:** __:__
**End Time:** __:__

**1. API Health Checks**
```bash
# Get API endpoint
API_ENDPOINT=$(kubectl get svc credit-api \
  -n credit-scoring-staging \
  -o jsonpath='{.status.loadBalancer.ingress[0].ip}')

# Test health endpoint
curl -X GET "http://${API_ENDPOINT}/health" \
  -H "Content-Type: application/json"

# Expected: {"status": "healthy", "database": "connected"}
```

**2. Submit Test Credit Application**
```bash
# Test data
cat > test-application.json <<'EOF'
{
  "applicant_id": "TEST-DR-DRILL-001",
  "national_id": "GHA-000000000-0",
  "first_name": "DR",
  "last_name": "DrillTest",
  "date_of_birth": "1990-01-01",
  "phone_number": "+233200000000",
  "email": "dr.drill@test.com",
  "monthly_income": 5000.00,
  "monthly_expenses": 2000.00,
  "employment_status": "Employed",
  "requested_amount": 10000.00,
  "loan_purpose": "DR Drill Test"
}
EOF

# Submit application
curl -X POST "http://${API_ENDPOINT}/api/v1/applications" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${TEST_API_TOKEN}" \
  -d @test-application.json

# Record application_id: _______________________________
```

**3. Verify Data Persistence**
```sql
-- Query database to confirm test application was saved
SELECT * FROM credit_scoring.applications
WHERE applicant_id = 'TEST-DR-DRILL-001';

-- Application found: YES / NO
-- Data accurate: YES / NO
```

#### Phase 7: Cleanup & Documentation (30 minutes)

**Start Time:** __:__
**End Time:** __:__

**1. Restore Staging to Normal**
```bash
# Option 1: Restart original staging database
az postgres flexible-server start \
  --resource-group payswitch-creditscore-staging-data-rg \
  --name <original-staging-postgres>

# Option 2: Keep DR database as new staging (if better)
# (Update DNS/configuration permanently)

# Update application to point back to original
kubectl create secret generic postgres-connection \
  --from-literal=connection-string="<original-connection-string>" \
  --namespace credit-scoring-staging \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl rollout restart deployment/credit-api -n credit-scoring-staging
```

**2. Delete DR Resources (Optional - Keep for Testing)**
```bash
# If using temporary DR resources:
az postgres flexible-server delete \
  --resource-group payswitch-creditscore-staging-dr-rg \
  --name payswitch-creditscore-staging-postgres-dr \
  --yes

# Or keep for next quarter's drill
```

**3. Cleanup Test Data**
```sql
-- Remove test records from database
DELETE FROM credit_scoring.applications
WHERE applicant_id = 'TEST-DR-DRILL-001';

-- Keep DR test records for audit
-- (Do NOT delete from dr_test_records table)
```

### Post-Drill Analysis (Within 48 Hours)

**1. Calculate Metrics**

| Metric | Target | Actual | Pass/Fail |
|--------|--------|--------|-----------|
| Time to detect failure | <5 min | __:__ min | ☐ Pass ☐ Fail |
| Time to initiate restore | <15 min | __:__ min | ☐ Pass ☐ Fail |
| Database restore duration | <2 hours | __:__ hours | ☐ Pass ☐ Fail |
| Application reconfiguration | <1 hour | __:__ min | ☐ Pass ☐ Fail |
| **Total RTO (Recovery Time)** | **<4 hours** | **__:__ hours** | **☐ Pass ☐ Fail** |
| Data loss (time) | <15 min | __:__ min | ☐ Pass ☐ Fail |
| Data integrity | 100% | __% | ☐ Pass ☐ Fail |

**2. Document Issues Encountered**

| Issue # | Description | Impact | Root Cause | Resolution | Owner |
|---------|-------------|--------|------------|------------|-------|
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |

**3. Lessons Learned**

**What Went Well:**
1.
2.
3.

**What Could Be Improved:**
1.
2.
3.

**Action Items:**

| Action | Owner | Due Date | Priority |
|--------|-------|----------|----------|
| Update runbook with new findings | | | High |
| Fix identified issues | | | High |
| Schedule follow-up training | | | Medium |
| Update DR documentation | | | Medium |

---

## 🎯 Drill #2: Full Region Failover (Q2)

**Scenario:** Complete West Europe region outage

**Duration:** 6-8 hours
**Participants:** All engineering teams, DevOps, Management
**Prerequisites:** Multi-region deployment configured, DNS failover ready

### Scope

This drill tests the complete failover of all services to the paired region (North Europe):

- **Compute:** AKS cluster in North Europe
- **Databases:** PostgreSQL geo-restore
- **Cache:** Redis with geo-replication
- **Storage:** Data Lake with GRS replication
- **Networking:** DNS/Traffic Manager failover
- **Monitoring:** Ensure visibility during failover

### Key Steps (High-Level)

1. **Pre-Drill:** Deploy complete infrastructure in North Europe
2. **Phase 1:** Simulate region outage (disable West Europe resources)
3. **Phase 2:** Initiate Traffic Manager failover
4. **Phase 3:** Restore databases in North Europe
5. **Phase 4:** Verify all services operational
6. **Phase 5:** End-to-end testing (full application flow)
7. **Phase 6:** Failback to West Europe
8. **Post-Drill:** Measure RTO, document findings

**Detailed procedures:** See `DR_DRILL_Q2_FULL_REGION_FAILOVER.md` (to be created before Q2)

---

## 🎯 Drill #3: Data Corruption Recovery (Q3)

**Scenario:** Accidental data deletion or corruption

**Duration:** 2-3 hours
**Participants:** Infrastructure, Database team, Data Engineering
**Prerequisites:** Point-in-time restore capability, backup verification

### Scope

This drill tests the ability to recover from data corruption without full system failover:

- **Point-in-time restore** to specific timestamp
- **Selective table restore** (single table recovery)
- **Data validation** after restore
- **Minimal downtime** approach

### Key Steps (High-Level)

1. **Pre-Drill:** Document current database state
2. **Phase 1:** Simulate data corruption (delete test records)
3. **Phase 2:** Identify corruption timestamp
4. **Phase 3:** Restore to new database (point-in-time)
5. **Phase 4:** Export affected tables from restore
6. **Phase 5:** Import corrected data to production
7. **Phase 6:** Validate data integrity
8. **Post-Drill:** Document recovery procedure

**Detailed procedures:** See `DR_DRILL_Q3_DATA_CORRUPTION.md` (to be created before Q3)

---

## 🎯 Drill #4: Complete System DR (Q4)

**Scenario:** Catastrophic failure requiring complete system rebuild

**Duration:** Full business day (8+ hours)
**Participants:** All teams, Executive management (observers)
**Prerequisites:** Complete infrastructure-as-code, backup verification

### Scope

This is the most comprehensive drill, testing the complete rebuild of the entire system from scratch:

- **Infrastructure:** Deploy all Azure resources via Bicep templates
- **Networking:** Recreate VNets, subnets, NSGs, firewalls
- **Compute:** Deploy AKS cluster, configure node pools
- **Data:** Restore all databases from backups
- **Applications:** Deploy all microservices, agents
- **Configuration:** Restore secrets, certificates, configurations
- **Validation:** Complete end-to-end testing

### Key Steps (High-Level)

1. **Pre-Drill:** Document everything (architecture, configs, data)
2. **Phase 1:** Assume zero existing infrastructure
3. **Phase 2:** Deploy infrastructure (Bicep templates)
4. **Phase 3:** Restore all data from backups
5. **Phase 4:** Deploy all applications
6. **Phase 5:** Configure networking and security
7. **Phase 6:** End-to-end testing (full workflows)
8. **Phase 7:** Load testing (verify performance)
9. **Post-Drill:** Comprehensive review and documentation

**Detailed procedures:** See `DR_DRILL_Q4_COMPLETE_SYSTEM.md` (to be created before Q4)

---

## 📊 Reporting & Metrics

### Drill Report Template

**Report ID:** DR-DRILL-Q[1-4]-YYYY
**Drill Date:** YYYY-MM-DD
**Drill Type:** [Database Failover / Full Region / Data Corruption / Complete System]
**Participants:** [List all participants]
**Duration:** [Total time]

#### Executive Summary

**Overall Result:** ☐ Pass ☐ Pass with Issues ☐ Fail

**Key Findings:**
-
-
-

**RTO Achievement:**
- Target: X hours
- Actual: Y hours
- Status: ☐ Met ☐ Exceeded ☐ Did Not Meet

**RPO Achievement:**
- Target: X minutes
- Actual: Y minutes
- Status: ☐ Met ☐ Exceeded ☐ Did Not Meet

#### Detailed Metrics

| Metric | Target | Actual | Variance | Status |
|--------|--------|--------|----------|--------|
| Detection time | | | | |
| Response time | | | | |
| Restore time | | | | |
| Validation time | | | | |
| **Total RTO** | | | | |
| Data loss (RPO) | | | | |
| Data integrity | | | | |

#### Issues Encountered

[Detailed list of all issues, organized by severity]

#### Recommendations

1. **High Priority:**
   -
   -

2. **Medium Priority:**
   -
   -

3. **Low Priority:**
   -
   -

#### Action Items

[Table of action items with owners and due dates]

#### Appendices

- Appendix A: Detailed timeline
- Appendix B: Screenshots/logs
- Appendix C: Updated procedures
- Appendix D: Team feedback

---

## 🔄 Continuous Improvement

### After Each Drill

**Week 1: Documentation**
- Compile drill report
- Update runbooks based on findings
- Share report with all stakeholders

**Week 2: Remediation**
- Assign action items to owners
- Schedule fixes for critical issues
- Update DR procedures

**Week 3: Training**
- Conduct lessons learned session
- Update training materials
- Cross-train team members

**Week 4: Validation**
- Verify all fixes implemented
- Update monitoring/alerting
- Schedule next drill

### Annual Review (December)

**Aggregate Metrics:**
- Compare all 4 quarterly drills
- Track RTO/RPO trends
- Identify systemic issues

**Strategic Planning:**
- Update DR strategy based on learnings
- Adjust RTO/RPO targets if needed
- Budget for DR improvements

**Management Presentation:**
- Present annual DR readiness report
- Demonstrate compliance with requirements
- Propose improvements for next year

---

## 📞 Emergency Contacts

### Internal Team

| Role | Name | Phone | Email |
|------|------|-------|-------|
| Infrastructure Lead | | +233-XXX-XXX | infrastructure@blache.com |
| Database Administrator | | +233-XXX-XXX | dba@blache.com |
| DevOps Lead | | +233-XXX-XXX | devops@blache.com |
| CTO | | +233-XXX-XXX | cto@blache.com |

### External Support

| Provider | Service | Phone | Email |
|----------|---------|-------|-------|
| Microsoft Azure | Azure Support | +1-800-MICROSOFT | azuresupport@microsoft.com |
| Microsoft | Premier Support | [TAM Number] | [TAM Email] |

---

## 📚 Related Documentation

- [Azure Infrastructure README](/azure-infrastructure/README.md)
- [Security & Compliance](/azure-infrastructure/docs/SECURITY_COMPLIANCE.md)
- [Backup & Recovery Procedures](/azure-infrastructure/docs/BACKUP_RECOVERY.md)
- [Incident Response Plan](/azure-infrastructure/docs/INCIDENT_RESPONSE.md)

---

## ✅ Pre-Drill Checklist (Complete 1 Week Before)

- [ ] Drill date scheduled and communicated
- [ ] All participants confirmed availability
- [ ] Staging environment prepared and tested
- [ ] Latest backups verified (within 24 hours)
- [ ] Runbook reviewed and printed
- [ ] Communication channels tested (Slack, Teams, Phone)
- [ ] Monitoring dashboards configured
- [ ] Test data prepared
- [ ] Cleanup procedures documented
- [ ] Post-drill meeting scheduled

---

**Document Status:** ✅ Complete
**Next Drill:** Q1 2025 (January) - Database Failover
**Owner:** Infrastructure Team

---

**Document Version:** 1.0
**Last Updated:** 2025-11-12
**Maintained By:** Blache Ltd Infrastructure Team
