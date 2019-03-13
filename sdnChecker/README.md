To depoy:

  - create or enter a namespace for dupVIPMonitor
  - create serviceaccount sdnchecker, like
  
          oc create sa sdnchecker

  - add secret to sa sdnchecker to pull image from registry
  
          oc secrets link sdnchecker $DOCKER_REGISTRY_SECRET --for=pull

  - add cluster role to sa sdnchecker
  
          oc adm policy add-cluster-role-to-user system:sdn-reader -z sdnchecker

  - add privileged to sa sdnchecker
  
          oc adm policy add-scc-to-user privileged -z sdnchecker

  - label all nodes need sdn checking with label sdnChecking=true, like
  
          oc label node node-01 sdnChecking=true

  - modify the following fields in dupvipmonitor.yml
  
    - TEST_DOCKER_REGISTRY
    - TEST_NAMESPACE
    - TEST_ROUTE

  - create with sdnchecker.yml
  
        oc create -f sdnchecker.yml