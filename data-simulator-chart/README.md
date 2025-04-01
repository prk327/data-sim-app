# Data Simulator Helm Chart

This Helm chart deploys the Data Simulator application to Kubernetes.

## Prerequisites

- Kubernetes 1.19+
- Helm 3.2.0+
- PV provisioner support in the underlying infrastructure (if using PVCs)

## Installation

### Using Helm Repository

```bash
helm repo add data-simulator https://your-helm-repo.com
helm install my-data-simulator data-simulator/data-simulator
```

### Using Local Chart

```bash
helm install my-data-simulator ./data-simulator
```

## Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `app.replicaCount` | Number of replicas | `1` |
| `app.image.repository` | Image repository | `your-registry/data-simulator` |
| `app.image.tag` | Image tag | `latest` |
| `vertica.host` | Vertica host | `host.docker.internal` |
| `vertica.port` | Vertica port | `5433` |
| `storage.config.enabled` | Enable config volume | `true` |
| `storage.config.mountPath` | Config file mount path | `/app/data_simulator/config/config.yaml` |
| `storage.columns.enabled` | Enable columns volume | `true` |
| `storage.columns.mountPath` | Columns directory mount path | `/app/data_simulator/config/columns` |
| `storage.tables.enabled` | Enable tables volume | `true` |
| `storage.tables.mountPath` | Tables directory mount path | `/app/data_simulator/config/tables` |

## Customizing the Deployment

### For Development with Host Path Volumes

```bash
helm install my-data-simulator ./data-simulator \
  --set storage.useHostPath=true \
  --set storage.hostPath.basePath="/path/to/your/local/config"
```

### Using Existing PVCs

```bash
helm install my-data-simulator ./data-simulator \
  --set storage.config.existingClaim="my-existing-config-pvc" \
  --set storage.columns.existingClaim="my-existing-columns-pvc" \
  --set storage.tables.existingClaim="my-existing-tables-pvc"
```

## Accessing the Application

After installation, follow the instructions displayed in the NOTES section to access your application.
```

## Deployment Instructions

1. **Package the chart**:
   ```bash
   helm package ./data-simulator
   ```

2. **Install the chart**:
   ```bash
   helm install data-simulator ./data-simulator-1.0.0.tgz
   ```

3. **For development with hostPath**:
   ```bash
   helm install data-simulator ./data-simulator-1.0.0.tgz \
     --set storage.useHostPath=true \
     --set storage.hostPath.basePath="/path/to/your/config"
   ```

4. **To upgrade**:
   ```bash
   helm upgrade data-simulator ./data-simulator-1.0.0.tgz
   ```

5. **To uninstall**:
   ```bash
   helm uninstall data-simulator
   ```