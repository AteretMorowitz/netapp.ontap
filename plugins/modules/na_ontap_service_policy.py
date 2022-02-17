#!/usr/bin/python

# (c) 2021, NetApp, Inc
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

'''
na_ontap_service_policy
'''

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = '''

module: na_ontap_service_policy

short_description: NetApp ONTAP service policy configuration
extends_documentation_fragment:
    - netapp.ontap.netapp.na_ontap
version_added: 21.7.0
author: NetApp Ansible Team (@carchi8py) <ng-ansibleteam@netapp.com>

description:
  - Add, modify, or remove service policies.
  - This module requires ONTAP 9.8 or later, and only supports REST.

options:
  state:
    description:
      - Whether the specified service policy should exist or not.
    choices: ['present', 'absent']
    type: str
    default: 'present'
  name:
    description:
      - The name of the service policy.
    required: true
    type: str
  ipspace:
    description:
      - Name of the ipspace.
      - Required for cluster-scoped service policies.
      - Optional for SVM-scoped service policies.
    type: str
  services:
    description:
      - List of services to associate to this service policy.
      - To remove all services, use "no_service".  No other value is allowed if no_service is present.
    type: list
    elements: str
    choices: ['cluster_core', 'intercluster_core', 'management_core', 'management_autosupport', 'management_bgp', 'management_ems', 'management_https',
              'management_ssh', 'management_portmap', 'data_core', 'data_nfs', 'data_cifs', 'data_flexcache', 'data_iscsi', 'data_s3_server', 'no_service']
  vserver:
    description:
      - The name of the vserver to use.
      - Omit this option for cluster scoped user accounts.
    type: str
  scope:
    description:
      - Set to "svm" for interfaces owned by an SVM. Otherwise, set to "cluster".
      - svm is assumed if vserver is set.
      - cluster is assumed is vserver is not set.
    type: str
    choices: ['cluster', 'svm']

notes:
  - This module supports check_mode.
  - This module is not idempotent if index is omitted.
'''

EXAMPLES = """

    - name: Create service policy
      netapp.ontap.na_ontap_service_policy:
        state: present
        account: SampleUser
        index: 0
        public_key: "{{ netapp_service_policy }}"
        vserver: ansibleVServer
        hostname: "{{ netapp_hostname }}"
        username: "{{ netapp_username }}"
        password: "{{ netapp_password }}"

    - name: Delete single service policy
      netapp.ontap.na_ontap_service_policy:
        state: absent
        account: SampleUser
        vserver: ansibleVServer
        hostname: "{{ netapp_hostname }}"
        username: "{{ netapp_username }}"
        password: "{{ netapp_password }}"

    - name: Modify single service policy
      netapp.ontap.na_ontap_service_policy:
        state: present
        account: SampleUser
        comment: ssh key for XXXX
        index: 0
        vserver: ansibleVServer
        hostname: "{{ netapp_hostname }}"
        username: "{{ netapp_username }}"
        password: "{{ netapp_password }}"
"""

RETURN = """
cd_action:
  description: whether a public key is created or deleted.
  returned: success
  type: str

modify:
  description: attributes that were modified if the key already exists.
  returned: success
  type: dict
"""

from ansible.module_utils.basic import AnsibleModule
import ansible_collections.netapp.ontap.plugins.module_utils.netapp as netapp_utils
from ansible_collections.netapp.ontap.plugins.module_utils.netapp_module import NetAppModule
from ansible_collections.netapp.ontap.plugins.module_utils.netapp import OntapRestAPI
import ansible_collections.netapp.ontap.plugins.module_utils.rest_response_helpers as rrh

HAS_NETAPP_LIB = netapp_utils.has_netapp_lib()


class NetAppOntapServicePolicy:
    """
    Common operations to manage public keys.
    """

    def __init__(self):
        self.use_rest = False
        argument_spec = netapp_utils.na_ontap_host_argument_spec()
        argument_spec.update(dict(
            state=dict(type='str', choices=['present', 'absent'], default='present'),
            name=dict(required=True, type='str'),
            ipspace=dict(type='str'),
            scope=dict(type='str', choices=['cluster', 'svm']),
            services=dict(type='list', elements='str',
                          choices=['cluster_core', 'intercluster_core', 'management_core', 'management_autosupport', 'management_bgp', 'management_ems',
                                   'management_https', 'management_ssh', 'management_portmap', 'data_core', 'data_nfs', 'data_cifs', 'data_flexcache',
                                   'data_iscsi', 'data_s3_server', 'no_service']),
            vserver=dict(type='str'),
        ))

        self.module = AnsibleModule(
            argument_spec=argument_spec,
            required_if=[
                ('scope', 'cluster', ['ipspace']),
                ('scope', 'svm', ['vserver']),
                ('vserver', None, ['ipspace']),
            ],
            required_one_of=[
                ('ipspace', 'vserver')
            ],
            supports_check_mode=True
        )

        self.na_helper = NetAppModule()
        self.parameters = self.na_helper.set_parameters(self.module.params)

        # REST API is required
        self.rest_api = OntapRestAPI(self.module)
        # check version
        self.rest_api.fail_if_not_rest_minimum_version('na_ontap_service_policy', 9, 8)
        self.validate_inputs()

    def validate_inputs(self):
        services = self.parameters.get('services')
        if services and 'no_service' in services:
            if len(services) > 1:
                self.module.fail_json(msg='Error: no other service can be present when no_service is specified.  Got: %s' % services)
            self.parameters['services'] = []

        scope = self.parameters.get('scope')
        if scope is None:
            self.parameters['scope'] = 'cluster' if self.parameters.get('vserver') is None else 'svm'
        elif scope == 'cluster' and self.parameters.get('vserver') is not None:
            self.module.fail_json(msg='Error: vserver cannot be set when "scope: cluster" is specified.  Got: %s' % self.parameters.get('vserver'))
        elif scope == 'svm' and self.parameters.get('vserver') is None:
            self.module.fail_json(msg='Error: vserver cannot be None when "scope: svm" is specified.')

    def get_service_policy(self):
        api = 'network/ip/service-policies'
        query = {
            'name': self.parameters['name'],
            'fields': 'name,uuid,ipspace,services,svm'
        }
        if self.parameters.get('vserver') is None:
            # vserser is empty for cluster
            query['scope'] = 'cluster'
        else:
            query['svm.name'] = self.parameters['vserver']

        if self.parameters.get('ipspace') is not None:
            query['ipspace.name'] = self.parameters['ipspace']

        response, error = self.rest_api.get(api, query)
        record, error = rrh.check_for_0_or_1_records(api, response, error)
        if error:
            msg = "Error in get_service_policy: %s" % error
            self.module.fail_json(msg=msg)
        return record

    def create_service_policy(self):
        api = 'network/ip/service-policies'
        body = {
            'name': self.parameters['name']
        }
        if self.parameters.get('vserver') is not None:
            body['svm.name'] = self.parameters['vserver']

        for attr in ('ipspace', 'scope', 'services'):
            value = self.parameters.get(attr)
            if value is not None:
                body[attr] = value

        dummy, error = self.rest_api.post(api, body)
        if error:
            msg = "Error in create_service_policy: %s" % error
            self.module.fail_json(msg=msg)

    def modify_service_policy(self, current, modify):
        # sourcery skip: dict-comprehension
        api = 'network/ip/service-policies/%s' % current['uuid']
        modify_copy = dict(modify)
        body = {}
        for key in modify:
            if key in ('services'):
                body[key] = modify_copy.pop(key)
        if modify_copy:
            msg = 'Error: attributes not supported in modify: %s' % modify_copy
            self.module.fail_json(msg=msg)
        if not body:
            msg = 'Error: nothing to change - modify called with: %s' % modify
            self.module.fail_json(msg=msg)

        dummy, error = self.rest_api.patch(api, body)
        if error:
            msg = "Error in modify_service_policy: %s" % error
            self.module.fail_json(msg=msg)

    def delete_service_policy(self, current):
        api = 'network/ip/service-policies/%s' % current['uuid']

        dummy, error = self.rest_api.delete(api)
        if error:
            msg = "Error in delete_service_policy: %s" % error
            self.module.fail_json(msg=msg)

    def get_actions(self):
        """Determines whether a create, delete, modify action is required
        """
        cd_action, modify, current = None, None, None
        current = self.get_service_policy()
        cd_action = self.na_helper.get_cd_action(current, self.parameters)
        if cd_action is None:
            modify = self.na_helper.get_modified_attributes(current, self.parameters)
        return cd_action, modify, current

    def apply(self):
        cd_action, modify, current = self.get_actions()

        if self.na_helper.changed and not self.module.check_mode:
            if cd_action == 'create':
                self.create_service_policy()
            elif cd_action == 'delete':
                self.delete_service_policy(current)
            elif modify:
                self.modify_service_policy(current, modify)

        self.module.exit_json(changed=self.na_helper.changed, cd_action=cd_action, modify=modify, scope=self.module.params)


def main():
    obj = NetAppOntapServicePolicy()
    obj.apply()


if __name__ == '__main__':
    main()
