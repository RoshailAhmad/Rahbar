# RAHBAR on Kubernetes: from a fresh cluster to a working pipeline

## 1. Cluster
```bash
minikube start --driver=docker --cni=calico --memory=6144 --cpus=4
minikube addons enable metrics-server
minikube addons enable ingress
minikube addons enable storage-provisioner     # creates the PVCs; without it they stay Pending
minikube addons enable default-storageclass
```

## 2. Images and manifests
```bash
make images                       # build api, indexer, ui and load them into minikube
kubectl apply -k k8s/overlays/dev
kubectl get pvc -n rahbar         # data-chroma-0, redis-data and data-lake must be Bound
```

## 3. The data lake (PVC `data-lake`, mounted at /data)
| Folder | Holds |
| --- | --- |
| /data/incoming | new documents waiting for ingestion |
| /data/lake | documents that passed verification |
| /data/quarantine | documents that failed verification (not indexed) |
| /data/archive | superseded versions, kept for rollback |
| /data/reports | one verification report per ingestion run |
| /data/results | evaluation result files |
| /data/traces | one JSON line per query |

Drop documents into the lake through the data-shell pod:
```bash
kubectl apply -f k8s/tools/data-shell.yaml
kubectl wait --for=condition=Ready pod/data-shell -n rahbar
kubectl cp <folder>/. rahbar/data-shell:/data/incoming/
```
