To depoy:

  - create or enter a namespace for dupVIPMonitor
  - create serviceaccount dupvipmonitor, like
  
          oc create sa dupvipmonitor

  - add secret to sa dupvipmonitor to pull image from registry
  
          oc secrets link dupvipmonitor $DOCKER_REGISTRY_SECRET --for=pull

  - add privileged to sa dupvipmonitor
  
          oc adm policy add-scc-to-user privileged -z dupvipmonitor

  - label nodes with label dupvipmonitor=true
  
          oc label node node-01 dupvipmonitor=true

  - modify the following fields in dupvipmonitor.yml
  
    - TEST_DOCKER_REGISTRY
    - TEST_NAMESPACE
    - TEST_ROUTE
    - TEST_VIPS

  - create with dupvipmonitor.yml
  
        oc create -f dupvipmonitor.yml
