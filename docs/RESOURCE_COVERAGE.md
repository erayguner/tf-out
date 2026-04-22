# GCP resource coverage (2026)

Source of truth for which GCP resources tf-out imports from Cloud Asset Inventory into Terraform today. Cross-checked against:

- Google's **canonical CAI asset-types list** (`cloud.google.com/asset-inventory/docs/asset-types`)
- **hashicorp/google** provider **v7.28.0** (1,064 resources) via the Terraform Registry MCP
- Terraform 1.5+ `import { }` block + 1.5+ `-generate-config-out` generation

## Coverage tiers

| Tier | Meaning | Output |
|---|---|---|
| **First-class** | Jinja template ships HCL + import block | `<domain>.tf` + `imports.tf` |
| **Import-only** | Canonical import ID known; no template yet | `imports.tf` only → operator runs `terraform plan -generate-config-out=auto_generated.tf` |
| **Manual** | No TF mapping (k8s.io/*, unsupported services) | Flagged in `MANUAL_RESOURCES.md` |

## Matrix

### IAM / Organisation

| Asset type | TF type | Tier |
|---|---|---|
| `cloudresourcemanager.googleapis.com/Project` | `google_project` | First-class |
| `cloudresourcemanager.googleapis.com/Folder` | `google_folder` | Import-only |
| `iam.googleapis.com/ServiceAccount` | `google_service_account` | First-class |
| `iam.googleapis.com/Role` | `google_project_iam_custom_role` | First-class |
| `iam.googleapis.com/WorkloadIdentityPool` | `google_iam_workload_identity_pool` | Import-only |
| `iam.googleapis.com/WorkloadIdentityPoolProvider` | `google_iam_workload_identity_pool_provider` | Import-only |
| `iam.googleapis.com/WorkforcePool` | `google_iam_workforce_pool` | Import-only |
| `iap.googleapis.com/TunnelDestGroup` | `google_iap_tunnel_dest_group` | Import-only |
| `identity.accesscontextmanager.googleapis.com/AccessLevel` | `google_access_context_manager_access_level` | Import-only |
| `identity.accesscontextmanager.googleapis.com/AccessPolicy` | `google_access_context_manager_access_policy` | Import-only |
| `identity.accesscontextmanager.googleapis.com/ServicePerimeter` | `google_access_context_manager_service_perimeter` | Import-only |
| `essentialcontacts.googleapis.com/Contact` | `google_essential_contacts_contact` | Import-only |

### Networking / VPC / DNS / Certs / Connectivity

40+ resources — full VPC, all load-balancer components, Cloud DNS, Network Connectivity Center, Certificate Manager, VPC Access, Interconnect/VPN.

Representative:

| Asset type | TF type | Tier |
|---|---|---|
| `compute.googleapis.com/Network` | `google_compute_network` | First-class |
| `compute.googleapis.com/Subnetwork` | `google_compute_subnetwork` | First-class |
| `compute.googleapis.com/Firewall` | `google_compute_firewall` | First-class |
| `compute.googleapis.com/FirewallPolicy` | `google_compute_firewall_policy` | Import-only |
| `compute.googleapis.com/Router` | `google_compute_router` | First-class |
| `compute.googleapis.com/BackendService` | `google_compute_backend_service` | Import-only |
| `compute.googleapis.com/UrlMap` | `google_compute_url_map` | Import-only |
| `compute.googleapis.com/TargetHttps{,Proxy}` + SslCertificate + SecurityPolicy | full LB | Import-only |
| `compute.googleapis.com/SecurityPolicy` | `google_compute_security_policy` | Import-only |
| `compute.googleapis.com/Interconnect{,Attachment}` | idem | Import-only |
| `compute.googleapis.com/VpnGateway` / `VpnTunnel` / `ExternalVpnGateway` | HA VPN stack | Import-only |
| `dns.googleapis.com/ManagedZone` | `google_dns_managed_zone` | First-class |
| `networkconnectivity.googleapis.com/Hub` / `Spoke` | NCC | Import-only |
| `certificatemanager.googleapis.com/Certificate` | `google_certificate_manager_certificate` | Import-only |
| `vpcaccess.googleapis.com/Connector` | `google_vpc_access_connector` | Import-only |

### Compute & workloads

| Asset type | TF type | Tier |
|---|---|---|
| `compute.googleapis.com/Instance` | `google_compute_instance` | First-class |
| `compute.googleapis.com/InstanceGroup` / `InstanceGroupManager` / `InstanceTemplate` | idem | First-class / Import-only |
| `compute.googleapis.com/Disk` / `RegionDisk` / `Snapshot` / `Image` | idem | Import-only |
| `run.googleapis.com/Service` | `google_cloud_run_v2_service` | First-class |
| `run.googleapis.com/Job` / `WorkerPool` / `DomainMapping` | idem | Import-only |
| `cloudfunctions.googleapis.com/Function` | `google_cloudfunctions2_function` | Import-only |
| `container.googleapis.com/Cluster` / `NodePool` | GKE | Import-only |
| `appengine.googleapis.com/Application` | `google_app_engine_application` | Import-only |
| `batch.googleapis.com/Job` | `google_batch_job` | Import-only |
| `workstations.googleapis.com/{WorkstationCluster,WorkstationConfig,Workstation}` | Cloud Workstations | Import-only |
| `gkehub.googleapis.com/{Membership,Feature,Fleet}` | GKE Hub | Import-only |

### Storage / data / analytics

| Asset type | TF type | Tier |
|---|---|---|
| `storage.googleapis.com/Bucket` | `google_storage_bucket` | Import-only |
| `bigquery.googleapis.com/{Dataset,Table,Routine}` | idem | Import-only |
| `sqladmin.googleapis.com/Instance` | `google_sql_database_instance` | Import-only |
| `spanner.googleapis.com/{Instance,Database}` | idem | Import-only |
| `bigtableadmin.googleapis.com/{Instance,Table}` | idem | Import-only |
| `firestore.googleapis.com/Database` | `google_firestore_database` | Import-only |
| `redis.googleapis.com/{Instance,Cluster}` | idem | Import-only |
| `memcache.googleapis.com/Instance` / `memorystore.googleapis.com/Instance` | idem | Import-only |
| `alloydb.googleapis.com/{Cluster,Instance,Backup}` | idem | Import-only |
| `file.googleapis.com/{Instance,Backup}` | Filestore | Import-only |
| `dataproc.googleapis.com/{Cluster,AutoscalingPolicy,WorkflowTemplate}` | idem | Import-only |
| `composer.googleapis.com/Environment` | Airflow | Import-only |
| `analyticshub.googleapis.com/{DataExchange,Listing}` | BQ Sharing | Import-only |
| `dataplex.googleapis.com/{Lake,Zone,Asset}` | idem | Import-only |
| `datastream.googleapis.com/{Stream,ConnectionProfile,PrivateConnection}` | idem | Import-only |
| `metastore.googleapis.com/{Service,Federation}` | Dataproc Metastore | Import-only |
| `storagetransfer.googleapis.com/TransferJob` | `google_storage_transfer_job` | Import-only |

### Security

| Asset type | TF type | Tier |
|---|---|---|
| `cloudkms.googleapis.com/KeyRing` | `google_kms_key_ring` | Import-only |
| `cloudkms.googleapis.com/CryptoKey` | `google_kms_crypto_key` | Import-only |
| `cloudkms.googleapis.com/EkmConnection` | `google_kms_ekm_connection` | Import-only |
| `secretmanager.googleapis.com/{Secret,SecretVersion}` | idem | Import-only |
| `privateca.googleapis.com/{CaPool,CertificateAuthority,Certificate,CertificateTemplate}` | CA Service | Import-only |
| `binaryauthorization.googleapis.com/{Policy,Attestor}` | idem | Import-only |
| `ids.googleapis.com/Endpoint` | Cloud IDS | Import-only |
| `backupdr.googleapis.com/{BackupVault,BackupPlan}` | idem | Import-only |

### DevOps / build / deploy

| Asset type | TF type | Tier |
|---|---|---|
| `artifactregistry.googleapis.com/Repository` | `google_artifact_registry_repository` | Import-only |
| `cloudbuild.googleapis.com/{BuildTrigger,Connection,Repository,WorkerPool}` | Build | Import-only |
| `clouddeploy.googleapis.com/{DeliveryPipeline,Target,Automation,CustomTargetType,DeployPolicy}` | Deploy | Import-only |
| `config.googleapis.com/Deployment` | Infra Manager | Import-only |
| `developerconnect.googleapis.com/{Connection,GitRepositoryLink}` | DevConnect | Import-only |

### Messaging / events / observability

| Asset type | TF type | Tier |
|---|---|---|
| `pubsub.googleapis.com/{Topic,Subscription,Schema}` | idem | Import-only |
| `cloudtasks.googleapis.com/Queue` | `google_cloud_tasks_queue` | Import-only |
| `eventarc.googleapis.com/{Trigger,Channel,MessageBus,Pipeline,Enrollment}` | idem | Import-only |
| `logging.googleapis.com/{LogSink,LogBucket,LogMetric,LogView}` | idem | Import-only |
| `monitoring.googleapis.com/{AlertPolicy,NotificationChannel,UptimeCheckConfig,Dashboard,Snooze}` | idem | Import-only |

### AI / ML

| Asset type | TF type | Tier |
|---|---|---|
| `aiplatform.googleapis.com/{Endpoint,Dataset,Model,Featurestore,Index,IndexEndpoint}` | Vertex AI | Import-only |

### Workflows / API management / other

| Asset type | TF type | Tier |
|---|---|---|
| `workflows.googleapis.com/Workflow` | `google_workflows_workflow` | Import-only |
| `apigateway.googleapis.com/{Api,Gateway,ApiConfig}` | API Gateway | Import-only |
| `apigee.googleapis.com/{Organization,Environment,Instance}` | Apigee | Import-only |
| `apikeys.googleapis.com/Key` | `google_apikeys_key` | Import-only |
| `healthcare.googleapis.com/{Dataset,FhirStore,DicomStore,Hl7V2Store}` | idem | Import-only |
| `firebase.googleapis.com/FirebaseProject` | `google_firebase_project` | Import-only |
| `notebooks.googleapis.com/{Instance,Runtime}` | Vertex AI Workbench | Import-only |
| `serviceusage.googleapis.com/Service` | `google_project_service` | First-class |

## Explicitly NOT covered

| Category | Why |
|---|---|
| `k8s.io/*`, `apps.k8s.io/*`, `batch.k8s.io/*`, `rbac.authorization.k8s.io/*`, `networking.k8s.io/*`, `storage.k8s.io/*`, `policy.k8s.io/*`, `autoscaling.k8s.io/*`, `admissionregistration.k8s.io/*`, `gateway.networking.k8s.io/*`, `extensions.k8s.io/*` | Intra-cluster Kubernetes objects. Managed by the `hashicorp/kubernetes` provider, not `hashicorp/google`. Classified as `manual` and flagged in MANUAL_RESOURCES.md. |
| CAI policy/runtime types (IAM_POLICY, OSCONFIG_ASSIGNMENT_REPORT, etc.) | Exported as IAM_POLICY sidecars in CAI. Attached to resources via `iam_policy`, not managed as standalone TF resources. |
| Data-plane jobs (`dataflow.googleapis.com/Job`, `dataproc.googleapis.com/Job`, `batch.googleapis.com/Job` executions) | Job executions are transient. Importing them as state is an anti-pattern; define jobs via templates / workflows. |
| Apigee proxies, Eventarc sub-resources, vmwareengine/gkeonprem | Importable, not in default discovery list. Extend `config/settings.yaml` and the REGISTRY if needed. |

## How to extend

Adding a new asset type is a **two-line change** in `src/discovery/classifiers.py`:

```python
REGISTRY["<service>.googleapis.com/<ResourceKind>"] = Mapping(
    "google_<service>_<snake_case>", True,
    import_id=_loc("<kind_plural>"),   # or _global / _regional / _zonal / _proj
)
```

Add the asset type to `config/settings.yaml → discovery.asset_types.<domain>` so CAI will inventory it.

## Workflow

```bash
# 1. Discovery + generation
uv run tf-out run --config config/settings.yaml

# 2. In generated-terraform/
terraform init

# 3. Auto-generate HCL for import-only resources
terraform plan -generate-config-out=auto_generated.tf

# 4. Review auto_generated.tf (Terraform writes `resource { }` blocks for
#    each import block that has no matching resource). First-class resources
#    already have HCL in <domain>.tf.

# 5. Apply
terraform apply

# 6. Optional: delete imports.tf after state contains all resources.
```

## Citations

All verified against `hashicorp/google` v7.28.0 via the Terraform Registry MCP on 2026-04-20. Individual resource doc IDs recorded in `docs/IMPORT_REVIEW.md` (for spot-checked resources); the rest follow canonical path shapes documented on the registry.
