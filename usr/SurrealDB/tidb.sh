kubectl create -f https://raw.githubusercontent.com/pingcap/tidb-operator/v1.6.0/manifests/crd.yaml

helm repo add pingcap https://charts.pingcap.org
helm repo update
helm install \
	-n tidb-operator \
    --create-namespace \
	tidb-operator \
	pingcap/tidb-operator \
	--version v1.6.0

kubectl create namespace tidb-cluster

kubectl apply -f tikv-cluster.yaml -n tidb-cluster

echo "Waiting for tikv cluster to be ready..."
sleep 240

while kubectl get tidbcluster -n tidb-cluster | grep -q "False"; do
    echo "Waiting for tikv cluster to be ready..."
    sleep 10
done

kubectl get svc/sdb-datastore-pd

export TIKV_URL=tikv://sdb-datastore-pd:2379

export SURREALDB_URL=http://$(kubectl get ingress surrealdb-tikv -o json | jq -r .status.loadBalancer.ingress[0].ip)