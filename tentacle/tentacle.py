#!/usr/bin/python2.7

import ast
from flask import Flask
from flask import request
import json
import os
import requests
import ruamel.yaml as yaml
import time


app = Flask(__name__)


def get_attr_chains():
    res_ovr = (
        'admissionConfig.pluginConfig.ClusterResourceOverride.configuration.')
    return {
        'cpuRequestToLimitPercent': res_ovr + 'cpuRequestToLimitPercent',
        'memoryRequestToLimitPercent': res_ovr + 'memoryRequestToLimitPercent',
        'subdomain': 'routingConfig.subdomain',
        'max-pods': 'kubeletArguments.max-pods',
        'kube-reserved': 'kubeletArguments.kube-reserved',
        'system-reserved': 'kubeletArguments.system-reserved'}


def get_view_items(role):
    return {
        'master': ['cpuRequestToLimitPercent', 'memoryRequestToLimitPercent',
                   'subdomain'],
        'node': ['kube-reserved', 'system-reserved', 'max-pods']}.get(role)


def get_default_confs(attr):
    return {
        'ClusterResourceOverride': {'configuration': {
            'apiVersion': 'v1', 'kind': 'ClusterResourceOverrideConfig'}}
        }.get(attr)


def validation(headers):
    origin_auth = headers.get('Authorization')
    if origin_auth:
        endpoint = 'https://172.30.0.1:443/api'
        headers = {"Authorization": origin_auth}
        req = requests.get(endpoint, headers=headers, verify=False)
        if req.status_code != 200:
            return 'Unauthorized in origin'
    else:
        inner_token = headers.get('inner_token')
        if not inner_token:
            return 'Unauthorized in origin'
        try:
            token = inner_token.decode('base64')
            node, timestamp = token.split(':')
            assert node == os.uname()[1]
            assert (time.time() - float(timestamp)) < 300
        except Exception:
            return 'Authorization failed, invalid inner token'


@app.route('/nodemap', methods=['POST'])
def update_nodemap():
    """ You should use this API to registry masters and nodes first, e.g.:
            curl -X POST http://0.0.0.0:9696/nodemap -d \
            '{"master": ["master1"], "node": ["node1","node2","node3"]}'
        If a master also have compute role, you can put it into node list.
    """

    msg = validation(request.headers)
    if msg:
        return msg, 401

    forwarded = 'forwarded' in request.data
    nodemap = ast.literal_eval(request.data)
    if forwarded:
        if type(nodemap) == str:
            nodemap = json.loads(nodemap)
    else:
        hostname = os.uname()[1]
        nodemap['forwarded'] = True
        data = json.dumps(nodemap)
        for master in nodemap['master']:
            if master ==  hostname:
                continue
            endpoint = 'http://%s:9696/nodemap' % master
            info = requests.post(endpoint, json=data)

    nodemap.pop('forwarded', False)
    with open('/var/lib/tentacle.dat', 'w+') as f:
        f.write(json.dumps(nodemap))
    return 'Nodes map updated'


def process_host(host, method, data, role):
    def get_confs(conf):
        ret = {}
        if conf and os.path.exists(conf):
            with open(conf) as f:
                ret = yaml.load(f, yaml.RoundTripLoader, preserve_quotes=True)
        return ret

    def set_confs(conf, data):
        with open(conf, 'w+') as f:
            yaml.dump(data, f, Dumper=yaml.RoundTripDumper)

    def get_conf_file(role):
        return {
            'node': '/etc/origin/node/node-config.yaml',
            'master': '/etc/origin/master/master-config.yaml'}.get(role, '')

    def update_configs(data, confs, conf_file):
        attr_chains = get_attr_chains()
        for k in data:
            if k in attr_chains:
                cursor = None
                for item in attr_chains[k].split('.'):
                    if item == k:
                        cursor[item] = data[k]
                    elif cursor:
                        if item not in cursor:
                            cursor[item] = get_default_confs(item)
                        cursor = cursor[item]
                    else:
                        cursor = confs[item]
        set_confs(conf_file, confs)

    def view_configs(data, confs):
        attr_chains = get_attr_chains()
        ret = {}
        for k in data:
            if k in attr_chains:
                cursor = None
                for item in attr_chains[k].split('.'):
                    if item == k:
                        ret[k] = cursor[item]
                    elif cursor:
                        if item not in cursor:
                            break
                        cursor = cursor[item]
                    else:
                        cursor = confs[item]
        return ret

    hostname = os.uname()[1]
    if host == hostname:
        conf_file = get_conf_file(role)
        confs = get_confs(conf_file)
        if not confs:
            return 'Target config file not exists', 404

        if method == 'POST':
            update_configs(data, confs, conf_file)
            if role == 'master':
                os.system(
                    'nohup systemctl restart origin-master-api '
                    'origin-master-controllers &')
                return 'Set master done'
            else:
                os.system('nohup systemctl restart origin-node &')
                return 'Set node done'
        else:
            return str(view_configs(get_view_items(role), confs))
    else:
        # we will work as proxy for request to target host
        hdr = {'inner_token': (
            '%s:%s' % (host, time.time())).encode('base64').strip()}
        if method == 'POST':
            endpoint = 'http://%(host)s:9696/%(role)s/%(host)s' % {
                'host': host, 'role': role}
            info = requests.post(endpoint, headers=hdr, json=data)
            return "Node set done"
        else:
            endpoint = 'http://%(host)s:9696/%(role)s/%(host)s' % {
                'host': host, 'role': role}
            info = requests.get(endpoint, headers=hdr).text.strip()
            return info


@app.route('/master/<host>', methods=['GET', 'POST'])
def process_master(host):
    msg = validation(request.headers)
    if msg:
        return msg, 401

    method = request.method
    data = ''
    if method == 'POST':
        data = ast.literal_eval(request.data)
    return process_host(host, method, data, "master")


@app.route('/node/<host>', methods=['GET', 'POST'])
def process_node(host):
    msg = validation(request.headers)
    if msg:
        return msg, 401

    method = request.method
    data = ''
    if method == 'POST':
        data = ast.literal_eval(request.data)
    return process_host(host, method, data, "node")


def process_members(method, data, role):
    if not os.path.exists('/var/lib/tentacle.dat'):
        return 'Not nodemap post yet', 404

    nodemap = ast.literal_eval(open('/var/lib/tentacle.dat').read())
    timestamp = time.time()
    if method == 'POST':
        for member in nodemap[role]:
            endpoint = 'http://%(host)s:9696/%(role)s/%(host)s' % {
                'host': member, 'role': role}
            hdr = {'inner_token': (
                '%s:%s' % (member, timestamp)).encode('base64').strip()}
            try:
                info = requests.post(endpoint, headers=hdr, json=data)
            except Exception:
                continue
        return "Masters/Nodes set done\n"
    else:
        all_info = {}
        for member in nodemap[role]:
            endpoint = 'http://%(host)s:9696/%(role)s/%(host)s' % {
                'host': member, 'role': role}
            hdr = {'inner_token': (
                '%s:%s' % (member, timestamp)).encode('base64').strip()}
            try:
                info = requests.get(endpoint, headers=hdr).text.strip()
            except Exception:
                continue
            all_info[member] = ast.literal_eval(info)
        return str(all_info)


@app.route('/masters', methods=['POST', 'GET'])
def process_masters():
    """ This API helps to get or set all masters config. """

    msg = validation(request.headers)
    if msg:
        return msg, 401

    method = request.method
    data = ''
    if method == 'POST':
        data = ast.literal_eval(request.data)
    return process_members(method, data, "master")


@app.route('/nodes', methods=['POST', 'GET'])
def process_nodes():
    """ This API helps to get or set all nodes config. """

    msg = validation(request.headers)
    if msg:
        return msg, 401

    method = request.method
    data = ''
    if method == 'POST':
        data = ast.literal_eval(request.data)
    return process_members(method, data, "node")


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=9696)
