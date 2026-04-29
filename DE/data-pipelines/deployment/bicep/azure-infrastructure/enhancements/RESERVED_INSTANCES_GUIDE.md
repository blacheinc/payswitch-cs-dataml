# Azure Reserved Instances - Cost Optimization Guide
## Credit Scoring & Decisioning Engine

**Document Version:** 1.0
**Last Updated:** 2025-11-12
**Maintained By:** Blache Ltd Infrastructure Team

---

## 📋 Executive Summary

Azure Reserved Instances (RIs) provide significant cost savings (up to 72%) compared to pay-as-you-go pricing for predictable workloads. This guide outlines the RI strategy for the PaySwitch Credit Scoring platform.

### Key Benefits

- **Cost Savings:** 30-72% reduction in compute costs
- **Budget Predictability:** Fixed pricing for 1-3 years
- **Flexibility:** Can exchange or cancel with flexibility
- **No Upfront Changes:** Same resources, lower cost

### Projected Annual Savings

| Environment | Pay-as-You-Go | With 3-Year RI | Annual Savings |
|-------------|---------------|----------------|----------------|
| **Production** | $42,480 | $18,241 | **$24,239 (57%)** |
| **Staging** | $8,496 | $3,648 | $4,848 (57%) |
| **Dev** | $4,248 | $4,248 | $0 (not recommended) |
| **Total** | $55,224 | $22,137 | **$33,087 (60%)** |

---

## 🎯 Reserved Instance Strategy

### Recommended Approach

**Phase 1: Production-First (Months 1-3)**
- Purchase 3-year RIs for production baseline capacity
- Coverage: 70% of production capacity
- Remaining 30% on pay-as-you-go for flexibility

**Phase 2: Staging Coverage (Months 4-6)**
- Purchase 1-year RIs for staging after validating production usage
- Coverage: 80% of staging capacity

**Phase 3: Optimization (Months 7-12)**
- Quarterly reviews and adjustments
- Exchange underutilized RIs as needed

### Why Not Dev Environment?

Development workloads are:
- Highly variable (turned off nights/weekends)
- Better suited for spot instances or pay-as-you-go
- Risk of unused capacity outweighs savings

---

## 💰 Detailed Cost Analysis

### 1. Azure Kubernetes Service (AKS)

#### Production Cluster

**Current Configuration:**
```yaml
Node Pool: Standard_D4s_v3
- vCPUs: 4
- RAM: 16 GB
- Node Count: 5 (baseline), auto-scale to 10
- Hours/Month: 730
```

**Cost Breakdown:**

| Pricing Model | Cost/Node/Month | 5 Nodes | Annual Cost |
|---------------|-----------------|---------|-------------|
| Pay-as-You-Go | $175.20 | $876 | $10,512 |
| 1-Year RI | $123.50 | $618 | $7,416 |
| 3-Year RI | $87.60 | $438 | $5,256 |

**Savings with 3-Year RI:** $5,256/year (50% savings)

**Recommendation:**
```bash
# Purchase 3-year RI for baseline 5 nodes
az reservations reservation-order purchase \
  --reserved-resource-type VirtualMachines \
  --sku-name Standard_D4s_v3 \
  --location westeurope \
  --quantity 5 \
  --term P3Y \
  --billing-plan Monthly
```

#### Staging Cluster

**Current Configuration:**
```yaml
Node Pool: Standard_D2s_v3
- Node Count: 2
- Cost/Node: $87.60 (pay-as-you-go)
- Annual Cost: $2,102
```

**Recommendation:**
- 1-year RI for 2 nodes: $1,486/year
- **Savings:** $616/year (29%)

---

### 2. Azure Database for PostgreSQL

#### Production Database

**Current Configuration:**
```yaml
SKU: GP_Standard_D4s_v3
- vCPUs: 4
- RAM: 16 GB
- High Availability: Zone-redundant (2x cost)
```

**Cost Breakdown:**

| Pricing Model | Cost/Month | Annual Cost |
|---------------|------------|-------------|
| Pay-as-You-Go | $438.00 | $5,256 |
| 1-Year RI | $306.60 | $3,679 |
| 3-Year RI | $218.40 | $2,621 |

**HA Configuration doubles the cost:**
- Pay-as-you-go: $10,512/year
- 3-Year RI: $5,242/year
- **Savings:** $5,270/year (50%)

**Recommendation:**
```bash
# Purchase 3-year RI for PostgreSQL Flexible Server
az postgres flexible-server reservation purchase \
  --sku-name GP_Standard_D4s_v3 \
  --location westeurope \
  --quantity 2 \
  --term P3Y \
  --billing-plan Monthly
```

---

### 3. Azure Cache for Redis

#### Production Redis (Premium P1)

**Current Configuration:**
```yaml
SKU: Premium P1
- Cache Size: 6 GB
- Replication: Enabled
- Zone Redundancy: 3 zones
```

**Cost Breakdown:**

| Pricing Model | Cost/Month | Annual Cost |
|---------------|------------|-------------|
| Pay-as-You-Go | $677.00 | $8,124 |
| 1-Year RI | $474.00 | $5,688 |
| 3-Year RI | $338.00 | $4,056 |

**Savings with 3-Year RI:** $4,068/year (50%)

**Recommendation:**
```bash
# Purchase 3-year RI for Redis Premium
az redis reservation purchase \
  --sku-name Premium \
  --sku-family P \
  --sku-capacity 1 \
  --location westeurope \
  --quantity 1 \
  --term P3Y \
  --billing-plan Monthly
```

---

### 4. Azure Machine Learning

#### Production Compute Clusters

**Current Configuration:**
```yaml
Training Cluster:
- SKU: Standard_NC6s_v3 (GPU)
- Instances: 0-4 (auto-scale)
- Usage: 10 hours/week average

Inference Cluster:
- SKU: Standard_D4s_v3
- Instances: 2 (always-on)
```

**Cost Analysis:**

**Training Cluster:**
- Highly variable workload
- **Recommendation:** Stay on pay-as-you-go
- Consider using spot instances (up to 90% savings)

**Inference Cluster:**
- Predictable 24/7 workload
- Pay-as-you-go: $2,102/year
- 3-Year RI: $1,051/year
- **Savings:** $1,051/year (50%)

**Recommendation:**
```bash
# Purchase 3-year RI for inference cluster
az ml compute reservation purchase \
  --sku-name Standard_D4s_v3 \
  --location westeurope \
  --quantity 2 \
  --term P3Y
```

---

### 5. Azure Data Factory

**Cost Structure:**
- Pay-per-use model (pipeline runs, data movement)
- No RI option available
- **Optimization Strategy:** Use incremental loads, efficient scheduling

**Current Monthly Cost:** $200 (prod)

**Alternative Optimizations:**
1. Schedule pipelines during off-peak hours
2. Use self-hosted integration runtime (uses existing VMs)
3. Implement incremental data loads
4. **Potential Savings:** 20-30% ($40-60/month)

---

### 6. Azure Service Bus

#### Production Namespace (Premium)

**Current Configuration:**
```yaml
SKU: Premium (1 Messaging Unit)
- Cost: $677/month
```

**RI Availability:** Not available for Service Bus

**Alternative Optimizations:**
1. Right-size messaging units based on throughput
2. Consider Standard tier for dev/staging ($10/month vs $677/month)
3. Use message batching to reduce operations

---

### 7. Cosmos DB (MongoDB API)

#### Production Database

**Current Configuration:**
```yaml
Throughput: 1,000 RU/s
- Cost: $60/month
- Annual: $720
```

**Cost Breakdown:**

| Pricing Model | Cost/Month | Annual Cost |
|---------------|------------|-------------|
| Pay-as-You-Go | $60.00 | $720 |
| 1-Year RI | $42.00 | $504 |
| 3-Year RI | $30.00 | $360 |

**Savings with 3-Year RI:** $360/year (50%)

**Recommendation:**
```bash
# Purchase reserved capacity for Cosmos DB
az cosmosdb sql reserve-capacity purchase \
  --resource-group payswitch-creditscore-prod-data-rg \
  --account-name <cosmos-account-name> \
  --reserved-capacity-properties \
    reservedResourceType=MongoDB \
    reservationOrderType=SingleUnit \
    reservationTerm=P3Y \
    reservationAutoRenew=true
```

---

## 📊 Summary: Recommended RI Purchases

### Production Environment (3-Year RIs)

| Resource | SKU | Quantity | Annual Savings |
|----------|-----|----------|----------------|
| AKS Nodes | Standard_D4s_v3 | 5 | $5,256 |
| PostgreSQL HA | GP_Standard_D4s_v3 | 2 | $5,270 |
| Redis Premium | Premium P1 | 1 | $4,068 |
| ML Inference | Standard_D4s_v3 | 2 | $1,051 |
| Cosmos DB | 1,000 RU/s | 1 | $360 |
| **Total Production Savings** | | | **$16,005** |

### Staging Environment (1-Year RIs)

| Resource | SKU | Quantity | Annual Savings |
|----------|-----|----------|----------------|
| AKS Nodes | Standard_D2s_v3 | 2 | $616 |
| PostgreSQL | GP_Standard_D2s_v3 | 1 | $378 |
| Redis Standard | Standard C2 | 1 | $143 |
| **Total Staging Savings** | | | **$1,137** |

### Grand Total Annual Savings: $17,142

---

## 🚀 Implementation Plan

### Month 1: Initial Assessment

**Week 1-2: Usage Analysis**
```bash
# Export last 90 days of usage data
az consumption usage list \
  --start-date 2025-08-12 \
  --end-date 2025-11-12 \
  --output table

# Analyze usage patterns
az advisor recommendation list \
  --category Cost \
  --output table
```

**Week 3-4: Capacity Planning**
1. Review auto-scaling metrics
2. Identify baseline capacity (always-on resources)
3. Document peak usage patterns
4. Calculate 70/30 split (RI vs. pay-as-you-go)

### Month 2: Production RI Purchase

**Priority Order:**
1. PostgreSQL (highest cost, predictable)
2. Redis (predictable cache workload)
3. AKS baseline nodes (5 nodes)
4. Cosmos DB (predictable storage)
5. ML inference cluster

**Purchase Script:**
```bash
#!/bin/bash
# purchase-production-ris.sh

RESOURCE_GROUP="payswitch-creditscore-prod-data-rg"
LOCATION="westeurope"
TERM="P3Y"
BILLING_PLAN="Monthly"

echo "Purchasing Production Reserved Instances..."

# 1. PostgreSQL HA (2 instances)
az postgres flexible-server reservation purchase \
  --sku-name GP_Standard_D4s_v3 \
  --location $LOCATION \
  --quantity 2 \
  --term $TERM \
  --billing-plan $BILLING_PLAN \
  --display-name "PaySwitch-Prod-PostgreSQL-HA"

# 2. Redis Premium
az redis reservation purchase \
  --sku-name Premium \
  --sku-family P \
  --sku-capacity 1 \
  --location $LOCATION \
  --quantity 1 \
  --term $TERM \
  --billing-plan $BILLING_PLAN \
  --display-name "PaySwitch-Prod-Redis-Premium"

# 3. AKS Nodes (5 baseline)
az reservations reservation-order purchase \
  --reserved-resource-type VirtualMachines \
  --sku-name Standard_D4s_v3 \
  --location $LOCATION \
  --quantity 5 \
  --term $TERM \
  --billing-plan $BILLING_PLAN \
  --display-name "PaySwitch-Prod-AKS-Baseline"

# 4. ML Inference Cluster
az ml compute reservation purchase \
  --sku-name Standard_D4s_v3 \
  --location $LOCATION \
  --quantity 2 \
  --term $TERM \
  --billing-plan $BILLING_PLAN \
  --display-name "PaySwitch-Prod-ML-Inference"

# 5. Cosmos DB Reserved Capacity
az cosmosdb sql reserve-capacity purchase \
  --resource-group $RESOURCE_GROUP \
  --account-name $(az cosmosdb list --resource-group $RESOURCE_GROUP --query "[0].name" -o tsv) \
  --reserved-capacity-properties \
    reservedResourceType=MongoDB \
    reservationOrderType=SingleUnit \
    reservationTerm=$TERM \
    reservationAutoRenew=true \
  --display-name "PaySwitch-Prod-CosmosDB"

echo "Production RI purchases complete!"
echo "Total annual savings: $16,005"
```

### Month 3: Validation & Staging

**Week 1-2: Monitor Production**
```bash
# Check RI utilization
az consumption reservation summary list \
  --grain daily \
  --reservation-order-id <order-id>

# Target: >95% utilization
```

**Week 3-4: Purchase Staging RIs**
- Same process as production
- Use 1-year term for flexibility
- Target: $1,137 annual savings

### Month 4-12: Optimization

**Quarterly Reviews (Q2, Q3, Q4):**
1. Review RI utilization reports
2. Identify underutilized RIs
3. Exchange or adjust as needed
4. Update capacity planning

---

## 📈 Monitoring & Management

### Daily Checks

**Azure Portal Dashboard:**
```
Cost Management → Reservations → Utilization
Target: >95% utilization
```

**Alert Configuration:**
```bash
# Create alert for low RI utilization
az monitor metrics alert create \
  --name "Low-RI-Utilization" \
  --resource-group payswitch-creditscore-prod-core-rg \
  --condition "avg UtilizationPercentage < 85" \
  --window-size 24h \
  --evaluation-frequency 1h \
  --action-group-ids <action-group-id>
```

### Monthly Reports

**Cost Analysis Report:**
```bash
# Generate monthly RI savings report
az consumption reservation summary list \
  --grain monthly \
  --start-date $(date -d "1 month ago" +%Y-%m-01) \
  --end-date $(date +%Y-%m-01) \
  --output table
```

**Key Metrics:**
- RI utilization percentage (target: >95%)
- Actual savings vs. projected savings
- Underutilized RIs (candidates for exchange)

### Quarterly Reviews

**Review Checklist:**
- [ ] Compare actual usage vs. RI capacity
- [ ] Identify underutilized RIs (utilization <80%)
- [ ] Review auto-scaling patterns
- [ ] Update capacity planning
- [ ] Consider RI exchanges/cancellations
- [ ] Update cost projections

---

## 🔄 RI Exchange & Flexibility

### Exchange Policy

**When to Exchange:**
1. Utilization consistently <80% for 3 months
2. Workload patterns change
3. Need different SKU or region

**How to Exchange:**
```bash
# Exchange RI for different SKU
az reservations reservation update \
  --reservation-order-id <order-id> \
  --reservation-id <reservation-id> \
  --applied-scope-type Shared

# Submit exchange request
az reservations exchange calculate \
  --reservation-id <current-ri-id> \
  --new-sku <new-sku-name> \
  --quantity <new-quantity>
```

**No Penalties:**
- Can exchange RIs for same or different SKU
- Can split or merge RIs
- Pro-rated refund for exchanges

### Cancellation Policy

**Cancellation Terms:**
- Up to $50,000 in cancellations per 12 months
- 12% early termination fee
- Pro-rated refund

**When to Cancel:**
1. Migrating to different cloud provider (unlikely)
2. Sunsetting the application
3. Major architecture change

---

## 💡 Best Practices

### 1. Start Conservative

**Recommendation:**
- Cover 60-70% of baseline capacity with RIs
- Keep 30-40% on pay-as-you-go for flexibility
- Gradually increase RI coverage as patterns stabilize

### 2. Use Scope Flexibility

**Scope Options:**
```yaml
Single Subscription: RI applies to specific subscription only
Shared: RI applies across all subscriptions in billing account
Resource Group: RI applies to specific resource group

Recommendation: Use "Shared" for maximum flexibility
```

### 3. Leverage Auto-Renewal

**Configuration:**
```bash
az reservations reservation update \
  --reservation-order-id <order-id> \
  --reservation-id <reservation-id> \
  --auto-renew true \
  --auto-renew-properties \
    renewTerm=P3Y \
    purchaseProperties=automatic
```

**Benefits:**
- Continues savings without manual renewal
- Can cancel auto-renewal anytime
- Locks in current pricing

### 4. Tag RIs for Tracking

**Tagging Strategy:**
```bash
az reservations reservation update \
  --reservation-order-id <order-id> \
  --reservation-id <reservation-id> \
  --tags \
    Environment=Production \
    Project=CreditScoring \
    CostCenter=Engineering \
    Owner=Infrastructure \
    ExpiryDate=2028-11-12
```

---

## 🎓 Training & Documentation

### Team Training

**Week 1: Finance Team**
- RI pricing models
- Budget forecasting with RIs
- Cost tracking and reporting

**Week 2: Engineering Team**
- RI utilization monitoring
- Capacity planning
- Exchange procedures

**Week 3: Management**
- ROI analysis
- Strategic planning
- Quarterly review process

### Documentation Updates

**Required Updates:**
1. Infrastructure deployment docs (include RI purchases)
2. Cost management runbook
3. Capacity planning procedures
4. Disaster recovery plan (account for RI commitments)

---

## 📞 Support & Resources

### Azure Support

**RI Purchase Support:**
- Azure Portal: Reservations → Help + Support
- Phone: +1-800-MICROSOFT
- Email: azuresupport@microsoft.com

**Billing Questions:**
- Azure Portal: Cost Management + Billing → Support
- Account Manager: [Your Microsoft Account Manager]

### Internal Contacts

**Infrastructure Team:**
- Lead: infrastructure@blache.com
- On-call: +233-XXX-XXXXXX

**Finance Team:**
- CFO: finance@blache.com
- Cost Management: cost-mgmt@blache.com

---

## 📚 Additional Resources

### Microsoft Documentation

- [Azure Reserved Instances Overview](https://learn.microsoft.com/en-us/azure/cost-management-billing/reservations/save-compute-costs-reservations)
- [RI Exchange Policy](https://learn.microsoft.com/en-us/azure/cost-management-billing/reservations/exchange-and-refund-azure-reservations)
- [RI Recommendations](https://learn.microsoft.com/en-us/azure/advisor/advisor-cost-recommendations)

### Tools

- **Azure Pricing Calculator:** https://azure.microsoft.com/en-us/pricing/calculator/
- **Azure Cost Management:** https://portal.azure.com/#blade/Microsoft_Azure_CostManagement/Menu/overview
- **Azure Advisor:** https://portal.azure.com/#blade/Microsoft_Azure_Expert/AdvisorMenuBlade/overview

---

## ✅ Implementation Checklist

### Pre-Purchase (Month 1)

- [ ] Export 90-day usage data
- [ ] Analyze usage patterns and identify baseline capacity
- [ ] Review auto-scaling metrics
- [ ] Calculate projected savings
- [ ] Get finance approval for 3-year commitment
- [ ] Set up cost tracking tags
- [ ] Create RI utilization dashboard

### Purchase (Month 2)

- [ ] Purchase production PostgreSQL RI (2 instances)
- [ ] Purchase production Redis RI (1 instance)
- [ ] Purchase production AKS RI (5 nodes)
- [ ] Purchase production ML inference RI (2 instances)
- [ ] Purchase production Cosmos DB reserved capacity
- [ ] Configure monitoring alerts
- [ ] Document RI details (order IDs, expiry dates)

### Validation (Month 3)

- [ ] Monitor RI utilization (target >95%)
- [ ] Validate savings in Cost Management
- [ ] Purchase staging RIs (1-year term)
- [ ] Update capacity planning documents
- [ ] Train team on RI management

### Ongoing (Quarterly)

- [ ] Review RI utilization reports
- [ ] Compare actual vs. projected savings
- [ ] Identify underutilized RIs
- [ ] Consider exchanges if needed
- [ ] Update capacity forecasts
- [ ] Update financial projections

---

**Document Status:** ✅ Complete
**Implementation Timeline:** 12 months
**Projected Annual Savings:** $17,142 (60% reduction)

**Next Action:** Schedule Month 1 usage analysis meeting with Infrastructure and Finance teams.

---

**Document Version:** 1.0
**Last Updated:** 2025-11-12
**Maintained By:** Blache Ltd Infrastructure Team
