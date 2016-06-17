# Copyright 2015 Metaswitch Networks
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from etcd import Client as EtcdClient
from etcd import EtcdKeyNotFound, EtcdResult, EtcdException, EtcdNotFile
import json
import unittest
from pycalico import netns

from mock import ANY
from netaddr import IPNetwork, IPAddress, AddrFormatError
from nose.tools import *
from nose_parameterized import parameterized
from mock import patch, Mock, call

from pycalico.datastore import (DatastoreClient, CALICO_V_PATH,
                                ETCD_SCHEME_ENV, ETCD_SCHEME_DEFAULT,
                                ETCD_ENDPOINTS_ENV,
                                ETCD_AUTHORITY_ENV, ETCD_CA_CERT_FILE_ENV,
                                ETCD_CERT_FILE_ENV, ETCD_KEY_FILE_ENV)
from pycalico.datastore_errors import DataStoreError, ProfileNotInEndpoint, ProfileAlreadyInEndpoint, \
    MultipleEndpointsMatch, InvalidBlockSizeError
from pycalico.datastore_datatypes import Rules, BGPPeer, IPPool, \
    Endpoint, Profile, Rule

TEST_HOST = "TEST_HOST"
TEST_ORCH_ID = "docker"
TEST_PROFILE = "TEST"
TEST_CONT_ID = "1234"
TEST_ENDPOINT_ID = "1234567890ab"
TEST_ENDPOINT_ID2 = "90abcdef1234"
TEST_HOST_PATH = CALICO_V_PATH + "/host/TEST_HOST"
TEST_HOST_IPV4_PATH = TEST_HOST_PATH + "/bird_ip"
IPV4_POOLS_PATH = CALICO_V_PATH + "/ipam/v4/pool/"
IPV6_POOLS_PATH = CALICO_V_PATH + "/ipam/v6/pool/"
TEST_PROFILE_PATH = CALICO_V_PATH + "/policy/profile/TEST/"
ALL_PROFILES_PATH = CALICO_V_PATH + "/policy/profile/"
ALL_ENDPOINTS_PATH = CALICO_V_PATH + "/host/"
ALL_HOSTS_PATH = CALICO_V_PATH + "/host/"
TEST_ORCHESTRATORS_PATH = CALICO_V_PATH + "/host/TEST_HOST/"
TEST_WORKLOADS_PATH = CALICO_V_PATH + "/host/TEST_HOST/workload/docker/"
TEST_ENDPOINT_PATH = CALICO_V_PATH + "/host/TEST_HOST/workload/docker/1234/" \
                                     "endpoint/1234567890ab"
TEST_CONT_ENDPOINTS_PATH = CALICO_V_PATH + "/host/TEST_HOST/workload/docker/" \
                                          "1234/"
TEST_CONT_PATH = CALICO_V_PATH + "/host/TEST_HOST/workload/docker/1234/"
CONFIG_PATH = CALICO_V_PATH + "/config/"

BGP_V_PATH = "/calico/bgp/v1"
BGP_GLOBAL_PATH = BGP_V_PATH + "/global"
BGP_PEERS_PATH = BGP_GLOBAL_PATH + "/peer_v4/"
BGP_HOSTS_PATH = BGP_V_PATH + "/host"
BGP_NODE_DEF_AS_PATH = BGP_GLOBAL_PATH + "/as_num"
BGP_NODE_MESH_PATH = BGP_GLOBAL_PATH + "/node_mesh"
TEST_BGP_HOST_PATH = BGP_HOSTS_PATH + "/TEST_HOST"
TEST_BGP_HOST_IPV4_PATH = TEST_BGP_HOST_PATH + "/ip_addr_v4"
TEST_BGP_HOST_IPV6_PATH = TEST_BGP_HOST_PATH + "/ip_addr_v6"
TEST_BGP_HOST_AS_PATH = TEST_BGP_HOST_PATH + "/as_num"
TEST_NODE_BGP_PEERS_PATH = TEST_BGP_HOST_PATH + "/peer_v4/"
TEST_NODE_BGP_PEERS_V6_PATH = TEST_BGP_HOST_PATH + "/peer_v6/"

IPAM_V4_PATH = "/calico/ipam/v2/host/THIS_HOST/ipv4/block/"
IPAM_V6_PATH = "/calico/ipam/v2/host/THIS_HOST/ipv6/block/"

# 4 endpoints, with 2 TEST profile and 2 UNIT profile.
EP_56 = Endpoint(TEST_HOST, "docker", TEST_CONT_ID, "567890abcdef",
                 "active", "AA-22-BB-44-CC-66")
EP_56.profile_ids = ["TEST"]
EP_78 = Endpoint(TEST_HOST, "docker", TEST_CONT_ID, "7890abcdef12",
                 "active", "11-AA-33-BB-55-CC")
EP_78.profile_ids = ["TEST"]
EP_90 = Endpoint(TEST_HOST, "docker", TEST_CONT_ID, "90abcdef1234",
                 "active", "1A-2B-3C-4D-5E-6E")
EP_90.profile_ids = ["UNIT"]
EP_12 = Endpoint(TEST_HOST, "docker", TEST_CONT_ID, TEST_ENDPOINT_ID,
                 "active", "11-22-33-44-55-66")
EP_12.profile_ids = ["UNIT"]

ETCD_ENV_DICT = {
    ETCD_AUTHORITY_ENV   : "127.0.0.2:4002",
    ETCD_SCHEME_ENV      : ETCD_SCHEME_DEFAULT,
    ETCD_ENDPOINTS_ENV   : "",
    ETCD_KEY_FILE_ENV    : "",
    ETCD_CERT_FILE_ENV   : "",
    ETCD_CA_CERT_FILE_ENV: ""
}

ETCD_ENV_DICT_ENDPOINTS = {
    ETCD_AUTHORITY_ENV   : "127.0.0.2:4002",
    ETCD_SCHEME_ENV      : ETCD_SCHEME_DEFAULT,
    ETCD_ENDPOINTS_ENV   : "http://1.2.3.4:5, http://6.7.8.9:10",
    ETCD_KEY_FILE_ENV    : "",
    ETCD_CERT_FILE_ENV   : "",
    ETCD_CA_CERT_FILE_ENV: ""
}

# A complicated set of Rules JSON for testing serialization / deserialization.
RULES_JSON = """
{
  "id": "PROF_GROUP1",
  "inbound_rules": [
    {
      "action": "allow",
      "src_tag": "PROF_GROUP1"
    },
    {
      "action": "allow",
      "src_net": "192.168.77.0/24"
    },
    {
      "action": "allow",
      "src_net": "192.168.0.0"
    },
    {
      "protocol": "udp",
      "src_tag": "SRC_TAG",
      "src_ports": [10, 20, 30],
      "src_net": "192.168.77.0/30",
      "dst_tag": "DST_TAG",
      "dst_ports": [20, 30, 40],
      "dst_net": "1.2.3.4",
      "icmp_type": 30,
      "action": "deny"
    }
  ],
  "outbound_rules": [
    {
      "action": "allow"
    }
  ]
}"""


class TestRule(unittest.TestCase):

    def test_create(self):
        """
        Test creating a rule from constructor.
        """
        rule1 = Rule(action="allow",
                     src_tag="TEST",
                     src_ports=[300, 400])
        assert_dict_equal({"action": "allow",
                           "src_tag": "TEST",
                           "src_ports": [300, 400]}, rule1)

    def test_to_json(self):
        """
        Test to_json() method.
        """
        rule1 = Rule(action="deny",
                     dst_net=IPNetwork("192.168.13.0/24"))
        json_str = rule1.to_json()
        expected = json.dumps({"action": "deny",
                               "dst_net": "192.168.13.0/24"})
        assert_equal(json_str, expected)

        rule2 = Rule(action="deny",
                     src_net="192.168.13.0/24")
        json_str = rule2.to_json()
        expected = json.dumps({"action": "deny",
                               "src_net": "192.168.13.0/24"})
        assert_equal(json_str, expected)

    @raises(KeyError)
    def test_wrong_keys(self):
        """
        Test that instantiating a Rule with mistyped keys fails.
        """
        _ = Rule(action="deny", dst_nets="192.168.13.0/24")

    @parameterized.expand([
        ({"action": "accept"}, True),
        ({"action": "deny"}, False),
        ({"protocol": "ftp"}, True),
        ({"protocol": None}, False),
        ({"src_tag": "ca$h"}, True),
        ({"dst_tag": "!nvalid"}, True),
        ({"src_ports": [-5, 6]}, True),
        ({"src_ports": [-5, "6:55"]}, True),
        ({"dst_ports": [65536]}, True),
        ({"dst_ports": [2, "-9:7"]}, True),
        ({"dst_ports": ["5:8"]}, False),
        ({"icmp_type": 300}, True),
        ({"icmp_type": 33}, False)
    ])
    def test_values(self, arg, raisesException):
        """
        Test that instantiating a Rule with action not allow|deny will fail.
        """
        if raisesException:
            self.assertRaises(ValueError, Rule, **arg)
        else:
            _ = Rule(**arg)

    def test_pprint(self):
        """
        Test pprint() method for human readable representation.
        """
        rule1 = Rule(action="allow",
                     src_tag="TEST",
                     src_ports=[300, 400, "100:200"])
        assert_equal("allow from ports 300,400,100:200 tag TEST",
                     rule1.pprint())

        rule2 = Rule(action="allow",
                     dst_tag="TEST",
                     dst_ports=[300, 400],
                     protocol="udp")
        assert_equal("allow udp to ports 300,400 tag TEST",
                     rule2.pprint())

        rule3 = Rule(action="deny",
                     src_net=IPNetwork("fd80::4:0/112"),
                     dst_ports=[80],
                     dst_net=IPNetwork("fd80::23:0/112"))
        assert_equal(
            "deny from cidr fd80::4:0/112 to ports 80 cidr fd80::23:0/112",
            rule3.pprint())

        rule4 = Rule(action="allow",
                     protocol="icmp",
                     icmp_code=100,
                     icmp_type=8,
                     src_net=IPNetwork("10/8"))
        assert_equal("allow icmp type 8 code 100 from cidr 10.0.0.0/8",
                     rule4.pprint())

        rule5 = Rule(action="allow",
                     protocol="icmpv6",
                     icmp_code=100,
                     icmp_type=128,
                     src_net=IPNetwork("10/8"))
        assert_equal("allow icmpv6 type 128 code 100 from cidr 10.0.0.0/8",
                     rule5.pprint())


class TestRules(unittest.TestCase):

    def test_rules(self):
        """
        Create a detailed set of rules, convert from and to json and compare
        the results.
        """
        # Convert a JSON blob into a Rules object.
        rules = Rules.from_json(RULES_JSON)

        # Convert the Rules object to JSON and then back again.
        new_json = rules.to_json()
        new_rules = Rules.from_json(new_json)

        # Compare the two rules objects.
        assert_equal(rules.id, new_rules.id)
        assert_equal(rules.inbound_rules,
                     new_rules.inbound_rules)
        assert_equal(rules.outbound_rules,
                     new_rules.outbound_rules)

        # Check the values of one of the inbound Rule objects.
        assert_equal(len(rules.inbound_rules), 4)
        inbound_rule = rules.inbound_rules[3]
        assert_equal(inbound_rule["protocol"], "udp")
        assert_equal(inbound_rule["src_tag"], "SRC_TAG")
        assert_equal(inbound_rule["src_ports"], [10, 20,30])
        assert_equal(inbound_rule["src_net"], IPNetwork("192.168.77.0/30"))
        assert_equal(inbound_rule["dst_tag"], "DST_TAG")
        assert_equal(inbound_rule["dst_net"], IPNetwork("1.2.3.4"))
        assert_equal(inbound_rule["icmp_type"], 30)
        assert_equal(inbound_rule["action"], "deny")


class TestEndpoint(unittest.TestCase):

    def test_to_json(self):
        """
        Test to_json() method.
        """
        endpoint1 = Endpoint(TEST_HOST, "docker", TEST_CONT_ID,
                             "aabbccddeeff112233",
                             "active", "11-22-33-44-55-66")
        assert_equal(endpoint1.endpoint_id, "aabbccddeeff112233")
        assert_equal(endpoint1.state, "active")
        assert_equal(endpoint1.mac, "11-22-33-44-55-66")
        assert_equal(endpoint1.profile_ids, [])  # Defaulted
        expected = {"state": "active",
                    "name": "caliaabbccddeef",
                    "mac": "11-22-33-44-55-66",
                    "profile_ids": [],
                    "labels": {},
                    "ipv4_nets": [],
                    "ipv6_nets": []}
        assert_dict_equal(json.loads(endpoint1.to_json()), expected)

    def test_from_json(self):
        """
        Test from_json() class method
          - Directly from JSON
          - From to_json() method of existing Endpoint.
        """
        expected = {"state": "active",
                    "name": "caliaabbccddeef",
                    "mac": "11-22-33-44-55-66",
                    "profile_id": "TEST23",
                    "ipv4_nets": ["192.168.3.2/32", "10.3.4.23/32"],
                    "ipv6_nets": ["fd20::4:2:1/128"]}
        endpoint = Endpoint.from_json(TEST_ENDPOINT_PATH, json.dumps(expected))
        assert_equal(endpoint.state, "active")
        assert_equal(endpoint.endpoint_id, TEST_ENDPOINT_ID)
        assert_equal(endpoint.mac, "11-22-33-44-55-66")
        assert_equal(endpoint.profile_ids, ["TEST23"])
        assert_set_equal(endpoint.ipv4_nets, {IPNetwork("192.168.3.2/32"),
                                              IPNetwork("10.3.4.23/32")})
        assert_set_equal(endpoint.ipv6_nets, {IPNetwork("fd20::4:2:1/128")})

        endpoint2 = Endpoint.from_json(TEST_ENDPOINT_PATH, endpoint.to_json())
        assert_equal(endpoint.state, endpoint2.state)
        assert_equal(endpoint.endpoint_id, endpoint2.endpoint_id)
        assert_equal(endpoint.mac, endpoint2.mac)
        assert_equal(endpoint.profile_ids, endpoint2.profile_ids)
        assert_set_equal(endpoint.ipv4_nets, endpoint2.ipv4_nets)
        assert_set_equal(endpoint.ipv6_nets, endpoint2.ipv6_nets)

    def test_operators(self):
        """
        Test Endpoint operators __eq__, __ne__ and copy.
        """
        endpoint1 = Endpoint(TEST_HOST, "docker", TEST_CONT_ID,
                             "aabbccddeeff112233",
                             "active", "11-22-33-44-55-66")
        endpoint2 = Endpoint(TEST_HOST, "docker", TEST_CONT_ID,
                             "aabbccddeeff112233",
                             "inactive", "11-22-33-44-55-66")
        endpoint3 = endpoint1.copy()

        assert_equal(endpoint1, endpoint3)
        assert_not_equal(endpoint1, endpoint2)
        assert_not_equal(endpoint1, 1)
        assert_false(endpoint1 == "this is not an endpoint")

    def test_matches(self):
        """
        Test Endpoint.matches() with various match conditions.
        """
        endpoint1 = Endpoint(TEST_HOST, "docker", TEST_CONT_ID,
                             "aabbccddeeff112233",
                             "active", "11-22-33-44-55-66")
        assert_true(endpoint1.matches(hostname=TEST_HOST,
                                      orchestrator_id="docker",
                                      workload_id=TEST_CONT_ID,
                                      endpoint_id="aabbccddeeff112233"))
        assert_false(endpoint1.matches(hostname="INVALID",
                                       orchestrator_id="docker",
                                       workload_id=TEST_CONT_ID,
                                       endpoint_id="aabbccddeeff112233"))
        assert_false(endpoint1.matches(hostname=TEST_HOST,
                                       orchestrator_id="INVALID",
                                       workload_id=TEST_CONT_ID,
                                       endpoint_id="aabbccddeeff112233"))
        assert_false(endpoint1.matches(hostname=TEST_HOST,
                                       orchestrator_id="docker",
                                       workload_id="INVALID",
                                       endpoint_id="aabbccddeeff112233"))
        assert_false(endpoint1.matches(hostname=TEST_HOST,
                                       orchestrator_id="docker",
                                       workload_id=TEST_CONT_ID,
                                       endpoint_id="INVALID"))

    def test_repr(self):
        """
        Test __repr__ returns the correct string value.
        """
        jsondata = {"state": "active",
                    "name": "caliaabbccddeef",
                    "mac": "11-22-33-44-55-66",
                    "profile_id": "TEST23",
                    "ipv4_nets": ["192.168.3.2/32", "10.3.4.23/32"],
                    "ipv6_nets": ["fd20::4:2:1/128"],
                    "ipv4_gateway": "10.3.4.2",
                    "ipv6_gateway": "2001:2:4a::1"}
        endpoint = Endpoint.from_json(TEST_ENDPOINT_PATH, json.dumps(jsondata))

        # Not the best test since this repeats the underlying implementation,
        # but checks that it isn't changed unexpectedly.
        assert_equal(endpoint.__repr__(),
                     "Endpoint(%s)" % endpoint.to_json())

    @patch('pycalico.netns.create_veth', autospec=True)
    @patch('pycalico.netns.move_veth_into_ns', autospec=True)
    @patch('pycalico.netns.add_ip_to_ns_veth', autospec=True)
    @patch('pycalico.netns.add_ns_default_route', autospec=True)
    @patch('pycalico.netns.get_ns_veth_mac', autospec=True)
    @patch('pycalico.datastore_datatypes.generate_cali_interface_name')
    def test_provision_veth(self, m_generate_cali_interface_name,
                            m_get_ns_veth_mac, m_add_ns_default_route,
                            m_add_ip_to_ns_veth, m_move_veth_into_ns,
                            m_create_veth):
        """
        Test provision_veth
        """
        # Set up mock objs
        m_generate_cali_interface_name.return_value = 'name'
        m_get_ns_veth_mac.return_value = 'mac'

        # Set up arguments
        endpoint = Endpoint(TEST_HOST, "docker", TEST_CONT_ID,
                             "aabbccddeeff112233",
                             "active", "11-22-33-44-55-66")
        ipv4 = IPAddress('1.1.1.1')
        ipv6 = IPAddress('201:db8::')
        endpoint.ipv4_nets.add(IPNetwork(ipv4))
        endpoint.ipv6_nets.add(IPNetwork(ipv6))
        ns_pid = 1000000
        veth_name_ns = 'veth_name_ns'

        # Call function under test
        namespace = netns.PidNamespace(ns_pid)
        function_return = endpoint.provision_veth(namespace, veth_name_ns)

        m_create_veth.assert_called_once_with('name', 'name')
        m_move_veth_into_ns.assert_called_once_with(namespace, 'name', veth_name_ns)
        m_add_ip_to_ns_veth.assert_has_calls([
            call(namespace, ipv6, veth_name_ns),
            call(namespace, ipv4, veth_name_ns)
        ])
        m_add_ns_default_route.assert_has_calls([
            call(namespace, endpoint.name, veth_name_ns)
        ])
        m_get_ns_veth_mac.assert_called_once_with(namespace, veth_name_ns)
        self.assertEqual(function_return, 'mac')


class TestBGPPeer(unittest.TestCase):
    def test_operator(self):
        """
        Test BGPPeer equality operator.
        """
        peer1 = BGPPeer("1.2.3.4", "22222")
        peer2 = BGPPeer(IPAddress("1.2.3.4"), 22222)
        peer3 = BGPPeer("1.2.3.5", 22222)
        peer4 = BGPPeer("1.2.3.4", 22226)
        assert_equal(peer1, peer2)
        assert_false(peer1 == peer3)
        assert_false(peer1 == peer4)
        assert_false(peer1 == "This is not a BGPPeer")


class TestIPPool(unittest.TestCase):
    def test_eq(self):
        """
        Test IPPool equality operator.
        """
        ippool1 = IPPool("1.2.3.4/24",
                         ipip=True, masquerade=True, ipam=False, disabled=True)
        ippool2 = IPPool(IPNetwork("1.2.3.8/24"),
                         ipip=True, masquerade=True, ipam=False, disabled=True)
        ippool3 = IPPool("1.2.3.4/24",
                         ipip=True, ipam=False)
        ippool4 = IPPool("1.2.3.4/24",
                         masquerade=True, ipam=False)
        ippool5 = IPPool("1.2.3.4/24",
                         ipip=True, masquerade=True)
        ippool6 = IPPool("1.2.3.4/24")
        assert_equal(ippool1, ippool2)
        assert_false(ippool1 == ippool3)
        assert_false(ippool1 == ippool4)
        assert_false(ippool1 == ippool5)
        assert_false(ippool1 == ippool6)
        assert_false(ippool1 == "This is not an IPPool")

    def test_contains(self):
        """
        Test IPPool "__contains__"operator.
        """
        assert_true(IPAddress("1.2.3.4") in IPPool("1.2.3.0/24"))
        assert_true("1.2.3.4" in IPPool("1.2.3.0/24"))

    def test_str(self):
        """
        Test __str__ returns just the CIDR.
        """
        assert_equal("1.2.3.0/24",
                      str(IPPool("1.2.3.4/24", ipip=True, masquerade=True)))

    def test_init(self):
        """
        Test __init__ allows correct IPPools
        """
        bad_cidr1 = "10.10.10.10/32"
        bad_cidr2 = "172.25.20.0/30"
        bad_cidr3 = "ffff::/128"
        good_cidr1 = "10.10.10.10/24"
        good_cidr2 = "ffff::/120"
        self.assertRaises(InvalidBlockSizeError,
                          IPPool, bad_cidr1, ipam=True)
        self.assertRaises(InvalidBlockSizeError,
                          IPPool, bad_cidr2, ipam=True)
        self.assertRaises(InvalidBlockSizeError,
                          IPPool, bad_cidr3, ipam=True)
        try:
            IPPool(good_cidr1, ipam=True)
            IPPool(good_cidr2, ipam=True)
            IPPool(bad_cidr1, ipam=False)
        except InvalidBlockSizeError:
            self.fail("Received unexpected AddressRangeNotAllowedError")


class TestDatastoreClient(unittest.TestCase):

    @patch("pycalico.datastore.os.getenv", autospec=True)
    @patch("pycalico.datastore.etcd.Client", autospec=True)
    def setUp(self, m_etcd_client, m_getenv):
        def m_getenv_return(key, *args):
            return ETCD_ENV_DICT[key]
        m_getenv.side_effect = m_getenv_return
        self.etcd_client = Mock(spec=EtcdClient)
        m_etcd_client.return_value = self.etcd_client
        self.datastore = DatastoreClient()
        m_etcd_client.assert_called_once_with(host="127.0.0.2", port=4002,
                                              protocol="http", cert=None,
                                              ca_cert=None)

    @patch('pycalico.datastore.get_hostname', autospec=True)
    def test_ensure_global_config(self, m_gethostname):
        """
        Test ensure_global_config when it doesn't already exist.
        """
        # Set up mocks
        m_gethostname.return_value = "THIS_HOST"

        int_prefix_path = CONFIG_PATH + "InterfacePrefix"
        log_file_path = CONFIG_PATH + "LogSeverityFile"
        log_screen_path = CONFIG_PATH + "LogSeverityScreen"
        log_file_path_path = CONFIG_PATH + "LogFilePath"
        ipip_path = CONFIG_PATH + "IpInIpEnabled"
        reporting_int_path = CONFIG_PATH + "ReportingIntervalSecs"
        self.etcd_client.read.side_effect = EtcdKeyNotFound

        # We only write the interface prefix if there is no entry in the
        # etcd database.  Note it is not sufficient to just check for the
        # existence of the config directory to determine whether we write
        # the interface prefix since the config directory may contain other
        # global configuration.
        self.datastore.ensure_global_config()
        expected_reads = [call(int_prefix_path),
                          call(BGP_NODE_DEF_AS_PATH),
                          call(BGP_NODE_MESH_PATH),
                          call(log_file_path),
                          call(log_screen_path),
                          call(log_file_path_path),
                          call(ipip_path),
                          call(reporting_int_path)]
        self.etcd_client.read.assert_has_calls(expected_reads)

        expected_writes = [call(int_prefix_path, "cali"),
                           call(IPAM_V4_PATH, None, dir=True),
                           call(IPV4_POOLS_PATH, None, dir=True),
                           call(IPAM_V6_PATH, None, dir=True),
                           call(IPV6_POOLS_PATH, None, dir=True),
                           call(BGP_NODE_DEF_AS_PATH, "64511"),
                           call(BGP_NODE_MESH_PATH, json.dumps({"enabled": True})),
                           call(log_file_path, "none"),
                           call(log_screen_path, "info"),
                           call(log_file_path_path, "none"),
                           call(ipip_path, "false"),
                           call(reporting_int_path, "0"),
                           call(CALICO_V_PATH + "/Ready", "true")]
        self.etcd_client.write.assert_has_calls(expected_writes)

    @patch('pycalico.datastore.get_hostname', autospec=True)
    def test_ensure_global_config_exists_dir(self, m_gethostname):
        """
        Test ensure_global_config when directory exists.
        """
        # Set up mocks
        m_gethostname.return_value = "THIS_HOST"

        def explode(path, value, **kwargs):
            if path == IPAM_V4_PATH:
                raise EtcdNotFile()

        self.etcd_client.write.side_effect = explode

        int_prefix_path = CONFIG_PATH + "InterfacePrefix"
        log_file_path = CONFIG_PATH + "LogSeverityFile"
        log_screen_path = CONFIG_PATH + "LogSeverityScreen"
        log_file_path_path = CONFIG_PATH + "LogFilePath"
        ipip_path = CONFIG_PATH + "IpInIpEnabled"
        reporting_int_path = CONFIG_PATH + "ReportingIntervalSecs"
        self.etcd_client.read.side_effect = EtcdKeyNotFound

        self.datastore.ensure_global_config()

        expected_writes = [call(int_prefix_path, "cali"),
                           call(IPAM_V4_PATH, None, dir=True),
                           call(IPV4_POOLS_PATH, None, dir=True),
                           call(IPAM_V6_PATH, None, dir=True),
                           call(IPV6_POOLS_PATH, None, dir=True),
                           call(BGP_NODE_DEF_AS_PATH, "64511"),
                           call(BGP_NODE_MESH_PATH, json.dumps({"enabled": True})),
                           call(log_file_path, "none"),
                           call(log_screen_path, "info"),
                           call(log_file_path_path, "none"),
                           call(ipip_path, "false"),
                           call(reporting_int_path, "0"),
                           call(CALICO_V_PATH + "/Ready", "true")]
        self.etcd_client.write.assert_has_calls(expected_writes)

    def test_ensure_global_config_exists(self):
        """
        Test ensure_global_config() when it already exists.
        """
        int_prefix_path = CONFIG_PATH + "InterfacePrefix"
        log_file_path = CONFIG_PATH + "LogSeverityFile"
        log_screen_path = CONFIG_PATH + "LogSeverityScreen"
        log_file_path_path = CONFIG_PATH + "LogFilePath"
        ipip_path = CONFIG_PATH + "IpInIpEnabled"
        self.datastore.ensure_global_config()
        expected_reads = [call(int_prefix_path),
                          call(BGP_NODE_DEF_AS_PATH),
                          call(BGP_NODE_MESH_PATH),
                          call(log_file_path),
                          call(log_screen_path),
                          call(log_file_path_path),
                          call(ipip_path)]
        self.etcd_client.read.assert_has_calls(expected_reads)

    def test_ensure_global_config_exists_etcd_exc(self):
        """
        Test ensure_global_config() when etcd raises an EtcdException.
        """
        self.etcd_client.read.side_effect = EtcdException
        self.assertRaises(DataStoreError, self.datastore.ensure_global_config)
        self.etcd_client.read.assert_called_once_with(
                                               CONFIG_PATH + "InterfacePrefix")

    def test_get_profile(self):
        """
        Test getting a named profile that exists.
        Test getting a named profile that doesn't exist raises a KeyError.
        """
        def mock_read(path):
            result = Mock(spec=EtcdResult)
            if path == TEST_PROFILE_PATH:
                return result
            elif path == TEST_PROFILE_PATH + "tags":
                result.value = '["TAG1", "TAG2", "TAG3"]'
                return result
            elif path == TEST_PROFILE_PATH + "rules":
                result.value = """
{
  "id": "TEST",
  "inbound_rules": [
    {"action": "allow", "src_net": "192.168.1.0/24", "src_ports": [200,2001]}
  ],
  "outbound_rules": [
    {"action": "allow", "src_tag": "TEST", "src_ports": [200,2001]}
  ]
}
"""
                return result
            else:
                raise EtcdKeyNotFound()
        self.etcd_client.read.side_effect = mock_read

        profile = self.datastore.get_profile("TEST")
        assert_equal(profile.name, "TEST")
        assert_set_equal({"TAG1", "TAG2", "TAG3"}, profile.tags)
        assert_equal(Rule(action="allow",
                          src_net=IPNetwork("192.168.1.0/24"),
                          src_ports=[200, 2001]),
                     profile.rules.inbound_rules[0])
        assert_equal(Rule(action="allow",
                          src_tag="TEST",
                          src_ports=[200, 2001]),
                     profile.rules.outbound_rules[0])

        assert_raises(KeyError, self.datastore.get_profile, "TEST2")

    def test_get_profile_no_tags_or_rules(self):
        """
        Test getting a named profile that exists, but has no tags or rules.
        """

        def mock_read(path):
            result = Mock(spec=EtcdResult)
            if path == TEST_PROFILE_PATH:
                return result
            else:
                raise EtcdKeyNotFound()
        self.etcd_client.read.side_effect = mock_read

        profile = self.datastore.get_profile("TEST")
        assert_equal(profile.name, "TEST")
        assert_set_equal(set(), profile.tags)
        assert_equal([], profile.rules.inbound_rules)
        assert_equal([], profile.rules.outbound_rules)

    @raises(KeyError)
    def test_remove_profile_doesnt_exist(self):
        """
        Remove profile when it doesn't exist.  Check it throws a KeyError.
        :return: None
        """
        self.etcd_client.delete.side_effect = EtcdKeyNotFound
        self.datastore.remove_profile(TEST_PROFILE)

    def test_profile_update_tags(self):
        """
        Test updating tags on an existing profile.
        :return:
        """

        profile = Profile("TEST")
        profile.tags = {"TAG4", "TAG5"}
        profile.rules = Rules(id="TEST",
                              inbound_rules=[
                                  Rule(action="allow", dst_ports=[12]),
                                  Rule(action="allow", protocol="udp"),
                                  Rule(action="deny")
                              ],
                              outbound_rules=[
                                  Rule(action="allow", src_ports=[23]),
                                  Rule(action="deny")
                              ])

        self.datastore.profile_update_tags(profile)
        self.etcd_client.write.assert_called_once_with(
            TEST_PROFILE_PATH + "tags",
            '["TAG4", "TAG5"]')

    def test_profile_update_rules(self):
        """
        Test updating rules on an existing profile.
        :return:
        """

        profile = Profile("TEST")
        profile.tags = {"TAG4", "TAG5"}
        profile.rules = Rules(id="TEST",
                              inbound_rules=[
                                  Rule(action="allow", dst_ports=[12]),
                                  Rule(action="allow", protocol="udp"),
                                  Rule(action="deny")
                              ],
                              outbound_rules=[
                                  Rule(action="allow", src_ports=[23]),
                                  Rule(action="deny")
                              ])

        self.datastore.profile_update_rules(profile)
        self.etcd_client.write.assert_called_once_with(
            TEST_PROFILE_PATH + "rules",
            profile.rules.to_json())

    @patch("pycalico.datastore.DatastoreClient.get_endpoint", autospec=True)
    @patch("pycalico.datastore.DatastoreClient.update_endpoint", autospec=True)
    def test_append_profiles_to_endpoint(self, m_update, m_get):
        """
        Test append_profiles_to_endpoint() to check profile_ids are updated.
        :return: None.
        """
        endpoint1 = Endpoint(TEST_HOST, "docker", TEST_CONT_ID,
                             "aabbccddeeff112233",
                             "active", "11-22-33-44-55-66")
        endpoint1.profile_ids = ["PROF1", "PROFA", "PROF2", "PROFB"]
        m_get.return_value = endpoint1

        endpoint2 = endpoint1.copy()
        endpoint2.profile_ids = ["PROF1", "PROFA", "PROF2", "PROFB",
                                 "PROFZ", "PROF5"]

        def update_endpoint(_ds, ep):
            assert_list_equal(ep.profile_ids,
                              ["PROF1", "PROFA", "PROF2",
                               "PROFB", "PROFZ", "PROF5"])
            assert_equal(endpoint1, endpoint2)
        m_update.side_effect = update_endpoint

        self.datastore.append_profiles_to_endpoint(["PROFZ", "PROF5"])
        assert_true(m_update.called)

    @patch("pycalico.datastore.DatastoreClient.get_endpoint", autospec=True)
    @patch("pycalico.datastore.DatastoreClient.update_endpoint", autospec=True)
    def test_append_profiles_to_endpoint_duplicate(self, m_update, m_get):
        """
        Test append_profiles_to_endpoint() with a duplicate profile.

        No update should occur.
        :return: None.
        """
        endpoint1 = Endpoint(TEST_HOST, "docker", TEST_CONT_ID,
                             "aabbccddeeff112233",
                             "active", "11-22-33-44-55-66")
        endpoint1.profile_ids = ["PROF1", "PROFA", "PROF2", "PROFB"]
        m_get.return_value = endpoint1

        self.assertRaises(ProfileAlreadyInEndpoint,
                          self.datastore.append_profiles_to_endpoint,
                          ["PROFZ", "PROFA"])
        assert_false(m_update.called)

    @patch("pycalico.datastore.DatastoreClient.get_endpoint", autospec=True)
    @patch("pycalico.datastore.DatastoreClient.update_endpoint", autospec=True)
    def test_set_profiles_on_endpoint(self, m_update, m_get):
        """
        Test set_profiles_on_endpoint() to check profile_ids are updated.
        :return: None.
        """
        endpoint1 = Endpoint(TEST_HOST, "docker", TEST_CONT_ID,
                             "aabbccddeeff112233",
                             "active", "11-22-33-44-55-66")
        endpoint1.profile_ids = ["PROF1", "PROFA", "PROF2", "PROFB"]
        m_get.return_value = endpoint1

        endpoint2 = endpoint1.copy()
        endpoint2.profile_ids = ["PROFZ", "PROF5"]

        def update_endpoint(ds, ep):
            assert_list_equal(ep.profile_ids,
                              ["PROFZ", "PROF5"])
            assert_equal(endpoint1, endpoint2)
        m_update.side_effect = update_endpoint

        self.datastore.set_profiles_on_endpoint(["PROFZ", "PROF5"])
        assert_true(m_update.called)

    @patch("pycalico.datastore.DatastoreClient.get_endpoint", autospec=True)
    @patch("pycalico.datastore.DatastoreClient.update_endpoint", autospec=True)
    def test_remove_profiles_from_endpoint(self, m_update, m_get):
        """
        Test remove_profiles_from_endpoint() to check profile_ids are updated.
        :return: None.
        """
        endpoint1 = Endpoint(TEST_HOST, "docker", TEST_CONT_ID,
                             "aabbccddeeff112233",
                             "active", "11-22-33-44-55-66")
        endpoint1.profile_ids = ["PROF1", "PROFA", "PROF2", "PROFB"]
        m_get.return_value = endpoint1

        endpoint2 = endpoint1.copy()
        endpoint2.profile_ids = ["PROFA", "PROFB"]

        def update_endpoint(_ds, ep):
            assert_list_equal(ep.profile_ids,
                              ["PROFA", "PROFB"])
            assert_equal(endpoint1, endpoint2)
        m_update.side_effect = update_endpoint

        self.datastore.remove_profiles_from_endpoint(["PROF1", "PROF2"])
        assert_true(m_update.called)

    @patch("pycalico.datastore.DatastoreClient.get_endpoint", autospec=True)
    @patch("pycalico.datastore.DatastoreClient.update_endpoint", autospec=True)
    def test_remove_profiles_to_endpoint_missing(self, m_update, m_get):
        """
        Test remove_profiles_from_endpoint() with an invalid profile.

        No update should occur.
        :return: None.
        """
        endpoint1 = Endpoint(TEST_HOST, "docker", TEST_CONT_ID,
                             "aabbccddeeff112233",
                             "active", "11-22-33-44-55-66")
        endpoint1.profile_ids = ["PROF1", "PROFA", "PROF2", "PROFB"]
        m_get.return_value = endpoint1

        self.assertRaises(ProfileNotInEndpoint,
                          self.datastore.remove_profiles_from_endpoint,
                          ["PROF1", "PROFZ"])
        assert_false(m_update.called)

    def test_create_host_exists(self):
        """
        Test create_host() when the .../workload key already exists.
        :return: None
        """
        def mock_read_success(path):
            result = Mock(spec=EtcdResult)
            if path == TEST_HOST_PATH + "/workload":
                return result
            else:
                assert False

        self.etcd_client.read.side_effect = mock_read_success

        ipv4 = "192.168.2.4"
        ipv6 = "fd80::4"
        bgp_as = 65531
        self.datastore.create_host(TEST_HOST, ipv4, ipv6, bgp_as)
        expected_writes = [call(TEST_HOST_IPV4_PATH, ipv4),
                           call(TEST_BGP_HOST_IPV4_PATH, ipv4),
                           call(TEST_BGP_HOST_IPV6_PATH, ipv6),
                           call(TEST_BGP_HOST_AS_PATH, bgp_as),
                           call(TEST_HOST_PATH +
                                "/config/DefaultEndpointToHostAction",
                                "RETURN"),
                           call(TEST_HOST_PATH + "/config/marker",
                                "created")]
        self.etcd_client.write.assert_has_calls(expected_writes,
                                                any_order=True)
        assert_equal(self.etcd_client.write.call_count, 6)

    def test_create_host_mainline(self):
        """
        Test create_host() when none of the keys exists (specifically,
        .../workload is checked and doesn't exist).
        :return: None
        """
        def mock_read(path):
            if path == CALICO_V_PATH + "/host/TEST_HOST/workload":
                raise EtcdKeyNotFound()
            else:
                assert False

        self.etcd_client.read.side_effect = mock_read
        self.etcd_client.delete.side_effect = EtcdKeyNotFound()

        ipv4 = "192.168.2.4"
        ipv6 = "fd80::4"
        bgp_as = None
        self.datastore.create_host(TEST_HOST, ipv4, ipv6, bgp_as)
        expected_writes = [call(TEST_HOST_IPV4_PATH, ipv4),
                           call(TEST_BGP_HOST_IPV4_PATH, ipv4),
                           call(TEST_BGP_HOST_IPV6_PATH, ipv6),
                           call(TEST_HOST_PATH +
                                "/config/DefaultEndpointToHostAction",
                                "RETURN"),
                           call(TEST_HOST_PATH + "/config/marker",
                                "created"),
                           call(TEST_HOST_PATH + "/workload",
                                None, dir=True)]
        self.etcd_client.write.assert_has_calls(expected_writes,
                                                any_order=True)
        assert_equal(self.etcd_client.write.call_count, 6)

    def test_get_per_host_config_mainline(self):
        value = self.datastore.get_per_host_config("hostname", "SomeConfig")
        assert_equal(value, self.etcd_client.read.return_value.value)
        assert_equal(self.etcd_client.read.mock_calls,
                     [call("/calico/v1/host/hostname/config/SomeConfig")])

    def test_get_per_host_config_not_exist(self):
        self.etcd_client.read.side_effect = EtcdKeyNotFound
        value = self.datastore.get_per_host_config("hostname", "SomeConfig")
        assert_is_none(value)

    def test_set_per_host_config_mainline(self):
        self.datastore.set_per_host_config("hostname", "SomeConfig", "foo")
        assert_equal(self.etcd_client.write.mock_calls,
                     [call("/calico/v1/host/hostname/config/SomeConfig",
                           "foo")])

    def test_set_per_host_config_none(self):
        # This exception should be suppressed
        self.etcd_client.delete.side_effect = EtcdKeyNotFound
        self.datastore.set_per_host_config("hostname", "SomeConfig", None)
        assert_equal(self.etcd_client.delete.mock_calls,
                     [call("/calico/v1/host/hostname/config/SomeConfig")])

    def test_remove_per_host_config_none(self):
        self.datastore.remove_per_host_config("hostname", "SomeConfig")
        assert_equal(self.etcd_client.delete.mock_calls,
                     [call("/calico/v1/host/hostname/config/SomeConfig")])

    def test_remove_host_mainline(self):
        """
        Test remove_host() when the key exists.
        :return:
        """
        self.datastore.remove_host(TEST_HOST)
        expected_deletes = [call(TEST_BGP_HOST_PATH + "/",
                                 dir=True,
                                 recursive=True),
                            call(TEST_HOST_PATH + "/",
                                 dir=True,
                                 recursive=True)]
        self.etcd_client.delete.assert_has_calls(expected_deletes)

    def test_remove_host_doesnt_exist(self):
        """
        Remove host when it doesn't exist.  Check it doesn't throw an
        exception.
        :return: None
        """
        self.etcd_client.delete.side_effect = EtcdKeyNotFound
        self.datastore.remove_host(TEST_HOST)

    def test_get_ip_pools(self):
        """
        Test getting IP pools from the datastore when there are some pools.
        :return: None
        """
        self.etcd_client.read.side_effect = mock_read_2_pools
        pools = self.datastore.get_ip_pools(4)
        assert_list_equal([IPPool("192.168.3.0/24"),
                           IPPool("192.168.5.0/24", ipam=False)],
                          pools)
        pools = self.datastore.get_ip_pools(4, ipam=True)
        assert_list_equal([IPPool("192.168.3.0/24")],
                          pools)

    def test_get_ip_pools_no_key(self):
        """
        Test getting IP pools from the datastore when the key doesn't exist.
        :return: None
        """
        def mock_read(path, recursive=False):
            assert_equal(path, IPV4_POOLS_PATH)
            assert_true(recursive)
            raise EtcdKeyNotFound()

        self.etcd_client.read.side_effect = mock_read
        pools = self.datastore.get_ip_pools(4)
        assert_list_equal([], pools)

    def test_get_ip_pools_no_pools(self):
        """
        Test getting IP pools from the datastore when the key is there but has
        no children.
        :return: None
        """
        self.etcd_client.read.side_effect = mock_read_no_pools
        pools = self.datastore.get_ip_pools(4)
        assert_list_equal([], pools)

    def test_get_ip_pool_config(self):
        """
        Test get_ip_pool_config where valid data is returned..
        """
        def mock_read(path):
            assert path == IPV4_POOLS_PATH + "1.2.0.0-16"
            result = Mock(spec=EtcdResult)
            result.key = path
            result.value = "{\"cidr\": \"1.2.0.0/16\"," \
                            "\"ipip\": \"tunl0\"," \
                            "\"masquerade\": true," \
                            "\"ipam\": false}"
            return result

        self.etcd_client.read.side_effect = mock_read
        config = self.datastore.get_ip_pool_config(4,
                                                   IPNetwork("1.2.3.4/16"))
        assert_equal(config,
                     IPPool("1.2.0.0/16", ipip=True, masquerade=True,
                            ipam=False))

    def test_get_ip_pool_config_doesnt_exist(self):
        """
        Test get_ip_pool_config where the pool does not exist.
        """
        self.etcd_client.read.side_effect = EtcdKeyNotFound
        self.assertRaises(KeyError,
                          self.datastore.get_ip_pool_config,
                          4, IPNetwork("1.2.3.4/1"))

    def test_add_ip_pool(self):
        """
        Test adding an IP pool when the directory exists, but pool doesn't.
        :return: None
        """
        # Return false for the IP in IP global setting.
        ipip_disabled_value = Mock(EtcdResult)
        ipip_disabled_value.value = "false"
        self.etcd_client.read.return_value = ipip_disabled_value

        pool = IPPool("192.168.100.5/24", ipip=True, masquerade=True)
        self.datastore.add_ip_pool(4, pool)
        self.etcd_client.write.assert_has_calls(
                             [call(CONFIG_PATH + "IpInIpEnabled", "true"),
                              call(IPV4_POOLS_PATH + "192.168.100.0-24", ANY)])
        raw_data = self.etcd_client.write.call_args[0][1]
        data = json.loads(raw_data)
        self.assertEqual(data, {'cidr': '192.168.100.0/24',
                                "ipip": "tunl0",
                                'masquerade': True})
        self.assertEqual(pool, IPPool.from_json(raw_data))

        self.etcd_client.write.reset_mock()
        pool = IPPool("192.168.100.5/24")
        self.datastore.add_ip_pool(4, pool)
        self.etcd_client.write.assert_called_once_with(
                                     IPV4_POOLS_PATH + "192.168.100.0-24", ANY)
        raw_data = self.etcd_client.write.call_args[0][1]
        data = json.loads(raw_data)
        self.assertEqual(data, {'cidr': '192.168.100.0/24'})
        self.assertEqual(pool, IPPool.from_json(raw_data))

    def test_add_ip_pool_key_not_found(self):
        """
        Test adding an IP pool when the directory doesn't exists.
        :return: None
        """
        # Return false for the IP in IP global setting.
        self.etcd_client.read.side_effect = EtcdKeyNotFound

        pool = IPPool("192.168.100.5/24", ipip=True, masquerade=True,
                      ipam=False, disabled=True)
        self.datastore.add_ip_pool(4, pool)
        self.etcd_client.write.assert_has_calls(
                             [call(CONFIG_PATH + "IpInIpEnabled", "true"),
                              call(IPV4_POOLS_PATH + "192.168.100.0-24", ANY)])
        raw_data = self.etcd_client.write.call_args[0][1]
        data = json.loads(raw_data)
        self.assertEqual(data, {'cidr': '192.168.100.0/24',
                                "ipip": "tunl0",
                                'masquerade': True,
                                "ipam": False,
                                "disabled": True})
        self.assertEqual(pool, IPPool.from_json(raw_data))

    def test_del_ip_pool_exists(self):
        """
        Test remove_ip_pool() when the pool does exist.
        :return: None
        """
        cidr = IPNetwork("192.168.3.1/24")
        self.datastore.remove_ip_pool(4, cidr)
        self.etcd_client.delete.assert_called_once_with(IPV4_POOLS_PATH + "192.168.3.0-24")

    def test_del_ip_pool_doesnt_exist(self):
        """
        Test remove_ip_pool() when the pool does not exist.
        :return: None
        """
        self.etcd_client.delete.side_effect = EtcdKeyNotFound
        cidr = IPNetwork("192.168.100.1/24")
        self.assertRaises(KeyError,
                          self.datastore.remove_ip_pool, 4, cidr)

    def test_profile_exists_true(self):
        """
        Test profile_exists() when it does.
        """
        def mock_read(path):
            assert_equal(path, TEST_PROFILE_PATH)
            return Mock(spec=EtcdResult)

        self.etcd_client.read.side_effect = mock_read
        assert_true(self.datastore.profile_exists("TEST"))

    def test_profile_exists_false(self):
        """
        Test profile_exists() when it doesn't exist.
        """
        def mock_read(path):
            assert_equal(path, TEST_PROFILE_PATH)
            raise EtcdKeyNotFound()

        self.etcd_client.read.side_effect = mock_read
        assert_false(self.datastore.profile_exists("TEST"))

    def test_create_profile(self):
        """
        Test create_profile()
        """
        self.datastore.create_profile("TEST")
        rules = Rules(id="TEST",
                      inbound_rules=[Rule(action="allow",
                                          src_tag="TEST")],
                      outbound_rules=[Rule(action="allow")])
        expected_calls = [call(TEST_PROFILE_PATH + "tags", '["TEST"]'),
                          call(TEST_PROFILE_PATH + "rules", rules.to_json())]
        self.etcd_client.write.assert_has_calls(expected_calls, any_order=True)

    def test_create_profile_with_rules(self):
        """
        Test create_profile() with rules specified
        """
        rules = Rules(id="TEST",
                      inbound_rules=[Rule(action="deny")],
                      outbound_rules=[Rule(action="allow")])
        self.datastore.create_profile("TEST", rules)
        expected_calls = [call(TEST_PROFILE_PATH + "tags", '["TEST"]'),
                          call(TEST_PROFILE_PATH + "rules", rules.to_json())]
        self.etcd_client.write.assert_has_calls(expected_calls, any_order=True)

    def test_delete_profile(self):
        """
        Test deleting a policy profile.
        """
        self.datastore.remove_profile("TEST")
        self.etcd_client.delete.assert_called_once_with(TEST_PROFILE_PATH,
                                                        recursive=True,
                                                        dir=True)

    def test_get_profile_names_2(self):
        """
        Test get_profile_names() when there are two profiles.
        """
        self.etcd_client.read.side_effect = mock_read_2_profiles
        profiles = self.datastore.get_profile_names()
        assert_set_equal(profiles, {"UNIT", "TEST"})

    def test_get_profile_names_no_key(self):
        """
        Test get_profile_names() when the key hasn't been set up.  Should
        return empty set and not raise a KeyError.
        """
        self.etcd_client.read.side_effect = mock_read_profiles_key_error
        profiles = self.datastore.get_profile_names()
        assert_set_equal(profiles, set())

    def test_get_profile_names_no_profiles(self):
        """
        Test get_profile_names() when there are no profiles.
        """
        self.etcd_client.read.side_effect = mock_read_no_profiles
        profiles = self.datastore.get_profile_names()
        assert_set_equal(profiles, set())

    def test_get_profile_members(self):
        """
        Test get_profile_members() when there are endpoints.
        """
        self.maxDiff = 1000
        self.etcd_client.read.side_effect = mock_read_4_endpoints
        members = self.datastore.get_profile_members("TEST")
        assert_list_equal(members, [EP_56, EP_78])

        members = self.datastore.get_profile_members("UNIT")
        assert_list_equal(members, [EP_90, EP_12])

        members = self.datastore.get_profile_members("UNIT_TEST")
        assert_list_equal(members, [])

    def test_get_profile_members_no_key(self):
        """
        Test get_profile_members() when the endpoints path has not been
        set up.
        """
        self.etcd_client.read.side_effect = mock_read_endpoints_key_error
        members = self.datastore.get_profile_members("UNIT_TEST")
        assert_list_equal(members, [])

    def test_get_endpoint_exists(self):
        """
        Test get_endpoint() for an endpoint that exists.
        """
        ep = Endpoint(TEST_HOST, TEST_ORCH_ID, TEST_CONT_ID, TEST_ENDPOINT_ID,
                      "active", "11-22-33-44-55-66")
        self.etcd_client.read.side_effect = mock_read_for_endpoint(ep)
        ep2 = self.datastore.get_endpoint(hostname=TEST_HOST,
                                          orchestrator_id=TEST_ORCH_ID,
                                          workload_id=TEST_CONT_ID,
                                          endpoint_id=TEST_ENDPOINT_ID)
        assert_equal(ep.to_json(), ep2.to_json())
        assert_equal(ep.endpoint_id, ep2.endpoint_id)

    def test_get_endpoint_doesnt_exist(self):
        """
        Test get_endpoint() for an endpoint that doesn't exist.
        """
        def mock_read(path, recursive=None):
            assert_true(recursive)
            assert_equal(path, TEST_ENDPOINT_PATH)
            raise EtcdKeyNotFound()
        self.etcd_client.read.side_effect = mock_read
        assert_raises(KeyError,
                      self.datastore.get_endpoint,
                      hostname=TEST_HOST, orchestrator_id=TEST_ORCH_ID,
                      workload_id=TEST_CONT_ID, endpoint_id=TEST_ENDPOINT_ID)

    def test_get_endpoints_multiple(self):
        """
        Test get_endpoints() with more than a single result.
        """

        self.etcd_client.read.side_effect = \
            get_mock_read_2_ep_for_cont(ALL_ENDPOINTS_PATH, True)
        self.assertRaises(MultipleEndpointsMatch, self.datastore.get_endpoint)

    def test_set_endpoint(self):
        """
        Test set_endpoint().
        """
        EP_12._original_json = ""
        self.datastore.set_endpoint(EP_12)
        self.etcd_client.write.assert_called_once_with(TEST_ENDPOINT_PATH,
                                                       EP_12.to_json())
        assert_equal(EP_12._original_json, EP_12.to_json())

    @patch('pycalico.datastore_datatypes.generate_cali_interface_name', autospec=True)
    def test_create_endpoint_ipv4(self, m_generate_cali_interface_name):
        """
        Test create_endpoint
        """
        test_ip = IPAddress('1.1.1.1')
        m_generate_cali_interface_name.return_value = "name"

        ep = Endpoint(TEST_HOST, TEST_ORCH_ID, TEST_CONT_ID, TEST_ENDPOINT_ID,
                      "active", "11-22-33-44-55-66")
        ep.ipv4_nets.add(IPNetwork(test_ip))

        ep2 = self.datastore.create_endpoint(
            TEST_HOST, TEST_ORCH_ID, TEST_CONT_ID, [test_ip], "11-22-33-44-55-66")

        assert_equal(ep.to_json(), ep2.to_json())

    @patch('pycalico.datastore_datatypes.generate_cali_interface_name', autospec=True)
    def test_create_endpoint_ipv6(self, m_generate_cali_interface_name):
        """
        Test create_endpoint
        """
        test_ip = IPAddress('201:db8::')

        m_generate_cali_interface_name.return_value = "name"

        ep = Endpoint(TEST_HOST, TEST_ORCH_ID, TEST_CONT_ID, TEST_ENDPOINT_ID,
                      "active", "11-22-33-44-55-66")
        ep.ipv6_nets.add(IPNetwork(test_ip))

        ep2 = self.datastore.create_endpoint(
            TEST_HOST, TEST_ORCH_ID, TEST_CONT_ID, [test_ip], "11-22-33-44-55-66")

        assert_equal(ep.to_json(), ep2.to_json())

    @patch('pycalico.datastore.DatastoreClient.get_ip_pools', autospec=True)
    def test_get_pool(self, m_get_ip_pools):
        """
        Test get_pool().
        """
        m_get_ip_pools.return_value = \
            [IPPool("192.168.3.0/24"), IPPool("192.168.5.0/24")]

        pool = self.datastore.get_pool(IPAddress("192.168.3.5"))

        assert_equal(pool, IPPool("192.168.3.0/24"))

    def test_remove_endpoint(self):
        """
        Test remove_endpoint().
        """
        self.datastore.remove_endpoint(EP_12)
        self.etcd_client.delete.assert_called_once_with(TEST_ENDPOINT_PATH,
                                                        recursive=True,
                                                        dir=True)

    def test_update_endpoint(self):
        """
        Test update_endpoint().
        """
        ep = EP_12.copy()
        original_json = ep.to_json()
        ep._original_json = original_json
        ep.profile_ids = ["a", "different", "set", "of", "ids"]
        assert_not_equal(ep._original_json, ep.to_json())

        self.datastore.update_endpoint(ep)
        self.etcd_client.write.assert_called_once_with(TEST_ENDPOINT_PATH,
                                                     ep.to_json(),
                                                     prevValue=original_json)
        assert_not_equal(ep._original_json, original_json)
        assert_equal(ep._original_json, ep.to_json())

    def test_get_endpoints_exists(self):
        """
        Test get_endpoints() passing in various numbers of parameters, with
        matching return results.
        """

        self.etcd_client.read.side_effect = \
            get_mock_read_2_ep_for_cont(ALL_ENDPOINTS_PATH, True)
        eps = self.datastore.get_endpoints()
        assert_equal(len(eps), 2)
        assert_equal(eps[0].to_json(), EP_12.to_json())
        assert_equal(eps[0].endpoint_id, EP_12.endpoint_id)
        assert_equal(eps[1].to_json(), EP_78.to_json())
        assert_equal(eps[1].endpoint_id, EP_78.endpoint_id)

        self.etcd_client.read.side_effect = \
            get_mock_read_2_ep_for_cont(TEST_ORCHESTRATORS_PATH, True)
        eps = self.datastore.get_endpoints(hostname=TEST_HOST)
        assert_equal(len(eps), 2)
        assert_equal(eps[0].to_json(), EP_12.to_json())
        assert_equal(eps[0].endpoint_id, EP_12.endpoint_id)
        assert_equal(eps[1].to_json(), EP_78.to_json())
        assert_equal(eps[1].endpoint_id, EP_78.endpoint_id)

        self.etcd_client.read.side_effect = \
            get_mock_read_2_ep_for_cont(TEST_WORKLOADS_PATH, True)
        eps = self.datastore.get_endpoints(hostname=TEST_HOST,
                                           orchestrator_id=TEST_ORCH_ID)
        assert_equal(len(eps), 2)
        assert_equal(eps[0].to_json(), EP_12.to_json())
        assert_equal(eps[0].endpoint_id, EP_12.endpoint_id)
        assert_equal(eps[1].to_json(), EP_78.to_json())
        assert_equal(eps[1].endpoint_id, EP_78.endpoint_id)

        self.etcd_client.read.side_effect = \
            get_mock_read_2_ep_for_cont(TEST_CONT_ENDPOINTS_PATH, True)
        eps = self.datastore.get_endpoints(hostname=TEST_HOST,
                                           orchestrator_id=TEST_ORCH_ID,
                                           workload_id=TEST_CONT_ID)
        assert_equal(len(eps), 2)
        assert_equal(eps[0].to_json(), EP_12.to_json())
        assert_equal(eps[0].endpoint_id, EP_12.endpoint_id)
        assert_equal(eps[1].to_json(), EP_78.to_json())
        assert_equal(eps[1].endpoint_id, EP_78.endpoint_id)

    def test_get_endpoints_no_matches(self):
        """
        Test get_endpoints() with etcd data returned, but non-matching data.
        """
        self.etcd_client.read.side_effect = \
              get_mock_read_2_ep_for_cont(TEST_WORKLOADS_PATH, True)
        eps = self.datastore.get_endpoints(hostname=TEST_HOST,
                                           orchestrator_id=TEST_ORCH_ID,
                                           endpoint_id="NOTVALID")
        assert_equal(len(eps), 0)

    def test_get_endpoints_doesnt_exist(self):
        """
        Test get_endpoints() for a container that doesn't exist.
        """
        def mock_read(path, recursive=None):
            assert_true(recursive)
            assert_equal(path, TEST_CONT_ENDPOINTS_PATH)
            raise EtcdKeyNotFound()
        self.etcd_client.read.side_effect = mock_read
        eps = self.datastore.get_endpoints(hostname=TEST_HOST,
                                           orchestrator_id=TEST_ORCH_ID,
                                           workload_id=TEST_CONT_ID)
        assert_equal(eps, [])


    def test_remove_all_data(self):
        """
        Test remove_all_data() when /calico does exist.
        """
        self.datastore.remove_all_data()
        self.etcd_client.delete.assert_called_once_with("/calico",
                                                        recursive=True,
                                                        dir=True)

    def test_remove_all_data_key_error(self):
        """
        Test remove_all_data() when delete() throws a KeyError.
        """
        self.etcd_client.delete.side_effect = EtcdKeyNotFound
        self.datastore.remove_all_data()  # should not throw exception.

    def test_remove_workload(self):
        """
        Test remove_workload()
        """
        self.datastore.remove_workload(TEST_HOST, TEST_ORCH_ID, TEST_CONT_ID)
        self.etcd_client.delete.assert_called_once_with(TEST_CONT_PATH,
                                                        recursive=True,
                                                        dir=True)

    @raises(KeyError)
    def test_remove_workload_missing(self):
        """
        Test remove_workload() raises a KeyError if the container does not
        exist.
        """
        self.etcd_client.delete.side_effect = EtcdKeyNotFound
        self.datastore.remove_workload(TEST_HOST, TEST_ORCH_ID, TEST_CONT_ID)

    def test_get_bgp_peers(self):
        """
        Test getting IP peers from the datastore when there are some peers.
        :return: None
        """
        self.etcd_client.read.side_effect = mock_read_2_peers
        peers = self.datastore.get_bgp_peers(4)
        assert_equal(peers, [BGPPeer("192.168.3.1", 32245),
                             BGPPeer("192.168.5.1", 32245)])

    def test_get_bgp_peers_no_key(self):
        """
        Test getting IP peers from the datastore when the key doesn't exist.
        :return: None
        """
        def mock_read(path):
            assert_equal(path, BGP_PEERS_PATH)
            raise EtcdKeyNotFound()

        self.etcd_client.read.side_effect = mock_read
        peers = self.datastore.get_bgp_peers(4)
        assert_list_equal([], peers)

    def test_get_bgp_peers_no_peers(self):
        """
        Test getting BGP peers from the datastore when the key is there but has
        no children.
        :return: None
        """
        self.etcd_client.read.side_effect = mock_read_no_bgppeers
        peers = self.datastore.get_bgp_peers(4)
        assert_list_equal([], peers)

    def test_add_bgp_peer(self):
        """
        Test adding an IP peer when the directory exists, but peer doesn't.
        :return: None
        """
        data = {"write": False}
        def mock_write(key, value):
            assert_equal(key, BGP_PEERS_PATH + "192.168.100.5")
            value = json.loads(value)
            assert_dict_equal(value,
                              {"as_num": "32245", "ip": "192.168.100.5"})
            data["write"] = True

        self.etcd_client.write.side_effect = mock_write
        peer = BGPPeer("192.168.100.5", 32245)
        self.datastore.add_bgp_peer(4, peer)
        assert_true(data["write"])

    def test_remove_bgp_peer_exists(self):
        """
        Test remove_bgp_peer() when the peer does exist.
        :return: None
        """
        self.etcd_client.delete = Mock()
        peer = IPAddress("192.168.3.1")
        self.datastore.remove_bgp_peer(4, peer)
        # 192.168.3.1 has a key ...v4/0 in the ordered list.
        self.etcd_client.delete.assert_called_once_with(
                                                BGP_PEERS_PATH + "192.168.3.1")

    def test_remove_bgp_peer_doesnt_exist(self):
        """
        Test remove_bgp_peer() when the peer does not exist.
        :return: None
        """
        self.etcd_client.delete.side_effect = EtcdKeyNotFound()
        peer = IPAddress("192.168.100.1")
        assert_raises(KeyError, self.datastore.remove_bgp_peer, 4, peer)

    def test_get_node_bgp_peer(self):
        """
        Test getting IP peers from the datastore when there are some peers.
        :return: None
        """
        self.etcd_client.read.side_effect = mock_read_2_node_peers
        peers = self.datastore.get_bgp_peers(4, hostname="TEST_HOST")
        assert_equal(peers, [BGPPeer("192.169.3.1", 32245),
                             BGPPeer("192.169.5.1", 32245)])

    def test_get_node_bgp_peer_no_key(self):
        """
        Test getting IP peers from the datastore when the key doesn't exist.
        :return: None
        """
        self.etcd_client.read.side_effect = mock_read_2_node_peers
        peers = self.datastore.get_bgp_peers(4, hostname="BLAH")
        assert_list_equal([], peers)

    def test_get_node_bgp_peer_no_peers(self):
        """
        Test getting BGP peers from the datastore when the key is there but has
        no children.
        :return: None
        """
        self.etcd_client.read.side_effect = mock_read_no_node_bgppeers
        peers = self.datastore.get_bgp_peers(4, hostname="TEST_HOST")
        assert_list_equal([], peers)

    def test_add_node_bgp_peer(self):
        """
        Test adding an IP peer when the directory exists, but peer doesn't.
        :return: None
        """
        data = {"write": False}
        def mock_write(key, value):
            assert_equal(key, TEST_NODE_BGP_PEERS_PATH + "192.169.100.5")
            value = json.loads(value)
            assert_dict_equal(value,
                              {"as_num": "32245", "ip": "192.169.100.5"})
            data["write"] = True

        self.etcd_client.write.side_effect = mock_write

        peer = BGPPeer(IPAddress("192.169.100.5"), 32245)
        self.datastore.add_bgp_peer(4, peer, hostname="TEST_HOST")
        assert_true(data["write"])

    def test_remove_node_bgp_peer_exists(self):
        """
        Test remove_node_bgp_peer() when the peer does exist.
        :return: None
        """
        self.etcd_client.delete = Mock()
        peer = IPAddress("192.168.3.1")
        self.datastore.remove_bgp_peer(4, peer, "TEST_HOST")
        # 192.168.3.1 has a key ...v4/0 in the ordered list.
        self.etcd_client.delete.assert_called_once_with(
                                      TEST_NODE_BGP_PEERS_PATH + "192.168.3.1")

    def test_remove_node_bgp_peer_doesnt_exist(self):
        """
        Test remove_node_bgp_peer() when the peer does not exist.
        :return: None
        """
        self.etcd_client.delete.side_effect = EtcdKeyNotFound()
        peer = IPAddress("192.168.100.1")
        assert_raises(KeyError, self.datastore.remove_bgp_peer,
                      4, peer, hostname="BLAH")

    def test_set_bgp_node_mesh(self):
        """
        Test set_bgp_node_mesh() stores the correct JSON when disabled and
        enabled.
        :return: None.
        """
        self.datastore.set_bgp_node_mesh(True)
        self.datastore.set_bgp_node_mesh(False)
        self.etcd_client.write.assert_has_calls([
                       call(BGP_NODE_MESH_PATH, json.dumps({"enabled": True})),
                       call(BGP_NODE_MESH_PATH, json.dumps({"enabled": False}))
                     ])

    def test_get_bgp_node_mesh(self):
        """
        Test get_bgp_node_mesh() returns the correct value based on the
        stored JSON.
        :return: None.
        """
        def mock_read(path):
            assert_equal(path, BGP_NODE_MESH_PATH)
            result = Mock(spec=EtcdResult)
            result.value = "{\"enabled\": true}"
            return result
        self.etcd_client.read = mock_read

        assert_true(self.datastore.get_bgp_node_mesh())

    def test_get_bgp_node_mesh_no_config(self):
        """
        Test get_bgp_node_mesh() returns the correct value when there is no
        mesh config.
        :return: None.
        """
        self.etcd_client.read.side_effect = EtcdKeyNotFound()
        assert_true(self.datastore.get_bgp_node_mesh())

    def test_set_default_node_as(self):
        """
        Test set_default_node_as() stores the correct value.
        :return: None.
        """
        self.datastore.set_default_node_as(12345)
        self.etcd_client.write.assert_called_once_with(BGP_NODE_DEF_AS_PATH,
                                                       "12345")

    def test_get_default_node_as(self):
        """
        Test get_default_node_as() returns the correct value based on the
        stored value.
        :return: None.
        """
        def mock_read(path):
            assert_equal(path, BGP_NODE_DEF_AS_PATH)
            result = Mock(spec=EtcdResult)
            result.value = "24245"
            return result
        self.etcd_client.read = mock_read

        assert_equal(self.datastore.get_default_node_as(), "24245")

    def test_get_default_node_as_no_config(self):
        """
        Test get_default_node_as() returns the correct value when there is no
        default AS config.
        :return: None.
        """
        self.etcd_client.read.side_effect = EtcdKeyNotFound()
        assert_equal(self.datastore.get_default_node_as(), "64511")

    def test_get_hosts_data(self):
        """
        Test get_hosts_data_dict returns expected values.
        :return: None.
        """
        def mock_read(path, *args, **kwargs):
            assert_equal(path, BGP_HOSTS_PATH+"/")
            result = Mock(spec=EtcdResult)
            ipv4_obj = Mock(spec=EtcdResult)
            ipv4_obj.key = TEST_BGP_HOST_IPV4_PATH
            ipv4_obj.value = "1.2.3.4"
            ipv6_obj = Mock(spec=EtcdResult)
            ipv6_obj.key = TEST_BGP_HOST_IPV6_PATH
            ipv6_obj.value = "aa:bb::ee"
            asnum_obj = Mock(spec=EtcdResult)
            asnum_obj.key = TEST_BGP_HOST_AS_PATH
            asnum_obj.value = "65111"
            peer_v4_obj = Mock(spec=EtcdResult)
            peer_v4_obj.key = TEST_NODE_BGP_PEERS_PATH + "10.10.10.10"
            peer_v4_obj.value = u'{"ip":"10.10.10.10", "as_num": "65111"}'
            peer_v6_obj = Mock(spec=EtcdResult)
            peer_v6_obj.key = TEST_NODE_BGP_PEERS_V6_PATH + "aaaa::ffff"
            peer_v6_obj.value = u'{"ip":"aaaa::ffff", "as_num": "65111"}'

            result.leaves = [ipv4_obj, ipv6_obj, asnum_obj,
                             peer_v4_obj, peer_v6_obj]
            return result

        self.etcd_client.read = mock_read

        expected = {"TEST_HOST": {"ip_addr_v4":"1.2.3.4",
                                  "ip_addr_v6":"aa:bb::ee",
                                  "as_num": "65111",
                                  "peer_v4": [{"ip":"10.10.10.10",
                                               "as_num": "65111"}],
                                  "peer_v6": [{"ip":"aaaa::ffff",
                                               "as_num": "65111"}]}}
        assert_equal(self.datastore.get_hosts_data_dict(), expected)

    def test_get_hosts_data(self):
        """
        Test get_hosts_data_dict returns an empty dict if no hosts exist
        :return: None.
        """
        def mock_read(path, *args, **kwargs):
            assert_equal(path, BGP_HOSTS_PATH+"/")
            result = Mock(spec=EtcdResult)
            result.leaves = []
            return result

        self.etcd_client.read = mock_read
        assert_equal(self.datastore.get_hosts_data_dict(), {})

    def test_get_hostnames_from_ips(self):
        """
        Test get_hostnames_from_ips returns correct dict when matches found
        """
        def mock_read(path, *args, **kwargs):
            assert_equal(path, BGP_HOSTS_PATH+"/")
            result = Mock(spec=EtcdResult)
            ipv4_obj = Mock(spec=EtcdResult)
            ipv4_obj.key = TEST_BGP_HOST_IPV4_PATH
            ipv4_obj.value = "1.2.3.4"
            ipv6_obj = Mock(spec=EtcdResult)
            ipv6_obj.key = TEST_BGP_HOST_IPV6_PATH
            ipv6_obj.value = "aa:bb::ee"

            result.leaves = [ipv4_obj, ipv6_obj]
            return result
        self.etcd_client.read = mock_read

        ip_list = ["1.2.3.4", "aa:bb::ee"]
        assert_equal(self.datastore.get_hostnames_from_ips(ip_list),
                     {"1.2.3.4":"TEST_HOST", "aa:bb::ee":"TEST_HOST"})

    def test_get_hostname_from_ips_no_hosts(self):
        """
        Test get_hostnames_from_ips raises a KeyError when no hosts are found.
        """
        self.etcd_client.read.side_effect = EtcdKeyNotFound

        assert_raises(KeyError, self.datastore.get_hostnames_from_ips,
                      ["1.2.3.4", "aa:bb::ee"])

    def test_get_host_bgp_ips(self):
        """
        Mainline test of get_host_bgp_ips().
        """
        def mock_read(path):
            if path == TEST_BGP_HOST_IPV4_PATH:
                result = Mock(spec=EtcdResult)
                result.value = "1.2.3.4"
                return result
            if path == TEST_BGP_HOST_IPV6_PATH:
                result = Mock(spec=EtcdResult)
                result.value = "aa:bb::ee"
                return result
            raise AssertionError("Unexpected path %s" % path)
        self.etcd_client.read = mock_read

        assert_equal(self.datastore.get_host_bgp_ips(TEST_HOST),
                     ("1.2.3.4", "aa:bb::ee"))

    def test_get_host_bgp_ips_not_found(self):
        """
        Test of get_host_bgp_ips() when not configured.
        """
        self.etcd_client.read.side_effect = EtcdKeyNotFound

        assert_raises(KeyError, self.datastore.get_host_bgp_ips, TEST_HOST)

    def test_get_host_as(self):
        """
        Check get_host_as() returns the AS number when configured and None
        when inheriting the default.
        """
        result = Mock(spec=EtcdResult)
        result.value = "1234"
        self.etcd_client.read.return_value = result
        assert_equal(self.datastore.get_host_as(TEST_HOST), "1234")

        self.etcd_client.read.side_effect = EtcdKeyNotFound
        assert_equal(self.datastore.get_host_as(TEST_HOST), None)


class TestDatastoreClientEndpoints(unittest.TestCase):

    @patch("pycalico.datastore.os.getenv", autospec=True)
    @patch("pycalico.datastore.etcd.Client", autospec=True)
    def test_endpoints_single_override(self, m_etcd_client, m_getenv):
        """ Test etcd endpoint overriding with a single endpoint."""
        etcd_env_dict = {
            ETCD_AUTHORITY_ENV   : "127.0.1.1:2380",
            ETCD_SCHEME_ENV      : "https",
            ETCD_ENDPOINTS_ENV   : "http://127.0.0.1:2379",
            ETCD_KEY_FILE_ENV    : "",
            ETCD_CERT_FILE_ENV   : "",
            ETCD_CA_CERT_FILE_ENV: ""
        }

        def m_getenv_return(key, *args):
            return etcd_env_dict[key]
        m_getenv.side_effect = m_getenv_return
        self.etcd_client = Mock(spec=EtcdClient)
        m_etcd_client.return_value = self.etcd_client
        self.datastore = DatastoreClient()
        m_etcd_client.assert_called_once_with(host="127.0.0.1",
                                              port=2379,
                                              protocol="http",
                                              cert=None,
                                              ca_cert=None)

    @patch("pycalico.datastore.os.getenv", autospec=True)
    @patch("pycalico.datastore.etcd.Client", autospec=True)
    def test_endpoints_multiple(self, m_etcd_client, m_getenv):
        """ Test etcd endpoint overriding with multiple endpoints."""
        etcd_env_dict = {
            ETCD_AUTHORITY_ENV   : "127.0.1.1:2380",
            ETCD_SCHEME_ENV      : "https",
            ETCD_ENDPOINTS_ENV   : "http://127.0.0.1:2379, http://127.0.1.1:2381",
            ETCD_KEY_FILE_ENV    : "",
            ETCD_CERT_FILE_ENV   : "",
            ETCD_CA_CERT_FILE_ENV: ""
        }

        def m_getenv_return(key, *args):
            return etcd_env_dict[key]
        m_getenv.side_effect = m_getenv_return
        self.etcd_client = Mock(spec=EtcdClient)
        m_etcd_client.return_value = self.etcd_client
        self.datastore = DatastoreClient()
        m_etcd_client.assert_called_once_with(host=(("127.0.0.1", 2379),
                                                    ("127.0.1.1", 2381)),
                                              protocol="http",
                                              cert=None,
                                              ca_cert=None,
                                              allow_reconnect=True)

    @patch("pycalico.datastore.os.getenv", autospec=True)
    @patch("pycalico.datastore.etcd.Client", autospec=True)
    def test_endpoints_proto_mismatch(self, m_etcd_client, m_getenv):
        """ Test mismatched protocols in etcd endpoints."""
        etcd_env_dict = {
            ETCD_AUTHORITY_ENV   : "127.0.1.1:2380",
            ETCD_SCHEME_ENV      : "https",
            ETCD_ENDPOINTS_ENV   : "http://127.0.0.1:2379, https://127.0.1.1:2381",
            ETCD_KEY_FILE_ENV    : "",
            ETCD_CERT_FILE_ENV   : "",
            ETCD_CA_CERT_FILE_ENV: ""
        }

        def m_getenv_return(key, *args):
            return etcd_env_dict[key]
        m_getenv.side_effect = m_getenv_return
        self.etcd_client = Mock(spec=EtcdClient)
        m_etcd_client.return_value = self.etcd_client
        self.assertRaises(DataStoreError, DatastoreClient)
        self.assertFalse(m_etcd_client.called)

    @patch("pycalico.datastore.os.getenv", autospec=True)
    @patch("pycalico.datastore.etcd.Client", autospec=True)
    def test_endpoints_format_invalid(self, m_etcd_client, m_getenv):
        """ Test invalid format of etcd endpoints."""
        etcd_env_dict = {
            ETCD_AUTHORITY_ENV   : "127.0.1.1:2380",
            ETCD_SCHEME_ENV      : "https",
            ETCD_ENDPOINTS_ENV   : "http:/ /127.0.0.1:2379\, https://127.0.1.1:2381",
            ETCD_KEY_FILE_ENV    : "",
            ETCD_CERT_FILE_ENV   : "",
            ETCD_CA_CERT_FILE_ENV: ""
        }

        def m_getenv_return(key, *args):
            return etcd_env_dict[key]
        m_getenv.side_effect = m_getenv_return
        self.etcd_client = Mock(spec=EtcdClient)
        m_etcd_client.return_value = self.etcd_client
        self.assertRaises(DataStoreError, DatastoreClient)
        self.assertFalse(m_etcd_client.called)
    @patch("pycalico.datastore.os.getenv", autospec=True)
    @patch("pycalico.datastore.etcd.Client", autospec=True)

    def test_endpoints_bad_proto(self, m_etcd_client, m_getenv):
        """ Test bad protocol for etcd endpoints."""
        etcd_env_dict = {
            ETCD_AUTHORITY_ENV   : "127.0.1.1:2380",
            ETCD_SCHEME_ENV      : "https",
            ETCD_ENDPOINTS_ENV   : "ftp://127.0.0.1:2379",
            ETCD_KEY_FILE_ENV    : "",
            ETCD_CERT_FILE_ENV   : "",
            ETCD_CA_CERT_FILE_ENV: ""
        }

        def m_getenv_return(key, *args):
            return etcd_env_dict[key]
        m_getenv.side_effect = m_getenv_return
        self.etcd_client = Mock(spec=EtcdClient)
        m_etcd_client.return_value = self.etcd_client
        self.assertRaises(DataStoreError, DatastoreClient)
        self.assertFalse(m_etcd_client.called)


class TestSecureDatastoreClient(unittest.TestCase):

    @patch("pycalico.datastore.os.getenv", autospec=True)
    @patch("pycalico.datastore.etcd.Client", autospec=True)
    @patch("pycalico.datastore.os.access", autospec=True)
    @patch("pycalico.datastore.os.path.isfile", autospec=True)
    def test_secure_etcd_no_cert_key(self, m_isfile, m_access, m_etcd_client,
                               m_getenv):
        """ Test validation for secure etcd with just a CA file. """
        m_isfile.return_value = True
        m_access.return_value = True
        ca_file = "/path/to/ca_file"
        etcd_env_dict = {
            ETCD_AUTHORITY_ENV   : "127.0.1.1:2380",
            ETCD_SCHEME_ENV      : "https",
            ETCD_ENDPOINTS_ENV   : "",
            ETCD_KEY_FILE_ENV    : "",
            ETCD_CERT_FILE_ENV   : "",
            ETCD_CA_CERT_FILE_ENV: ca_file
        }

        def m_getenv_return(key, *args):
            return etcd_env_dict[key]
        m_getenv.side_effect = m_getenv_return
        self.etcd_client = Mock(spec=EtcdClient)
        m_etcd_client.return_value = self.etcd_client
        self.datastore = DatastoreClient()
        m_etcd_client.assert_called_once_with(host="127.0.1.1",
                                              port=2380,
                                              protocol="https",
                                              cert=None,
                                              ca_cert=ca_file)

    @patch("pycalico.datastore.os.getenv", autospec=True)
    @patch("pycalico.datastore.etcd.Client", autospec=True)
    @patch("pycalico.datastore.os.access", autospec=True)
    @patch("pycalico.datastore.os.path.isfile", autospec=True)
    def test_secure_etcd_ca(self, m_isfile, m_access, m_etcd_client, m_getenv):
        """ Test validation for secure etcd with key, cert, and CA file. """
        m_isfile.return_value = True
        m_access.return_value = True
        key_file = "/path/to/key_file"
        cert_file = "/path/to/cert_file"
        ca_file = "/path/to/ca_file"
        etcd_env_dict = {
            ETCD_AUTHORITY_ENV   : "127.0.1.1:2380",
            ETCD_SCHEME_ENV      : "https",
            ETCD_ENDPOINTS_ENV   : "",
            ETCD_KEY_FILE_ENV    : key_file,
            ETCD_CERT_FILE_ENV   : cert_file,
            ETCD_CA_CERT_FILE_ENV: ca_file
        }

        def m_getenv_return(key, *args):
            return etcd_env_dict[key]
        m_getenv.side_effect = m_getenv_return
        self.etcd_client = Mock(spec=EtcdClient)
        m_etcd_client.return_value = self.etcd_client
        self.datastore = DatastoreClient()
        m_etcd_client.assert_called_once_with(host="127.0.1.1",
                                              port=2380,
                                              protocol="https",
                                              cert=(cert_file, key_file),
                                              ca_cert=ca_file)

    @patch("pycalico.datastore.os.getenv", autospec=True)
    @patch("pycalico.datastore.etcd.Client", autospec=True)
    @patch("pycalico.datastore.os.access", autospec=True)
    @patch("pycalico.datastore.os.path.isfile", autospec=True)
    def test_secure_etcd_bad_scheme(self, m_isfile, m_access,
                                    m_etcd_client, m_getenv):
        """
        Test validation for secure etcd fails when scheme is unrecognized.
        """
        m_isfile.return_value = True
        m_access.return_value = True
        etcd_env_dict = {
            ETCD_AUTHORITY_ENV   : "127.0.1.1:2380",
            ETCD_SCHEME_ENV      : "htt",
            ETCD_ENDPOINTS_ENV   : "",
            ETCD_KEY_FILE_ENV    : "",
            ETCD_CERT_FILE_ENV   : "",
            ETCD_CA_CERT_FILE_ENV: ""
        }

        def m_getenv_return(key, *args):
            return etcd_env_dict[key]
        m_getenv.side_effect = m_getenv_return
        self.etcd_client = Mock(spec=EtcdClient)
        m_etcd_client.return_value = self.etcd_client
        self.assertRaises(DataStoreError, DatastoreClient)
        self.assertFalse(m_etcd_client.called)

    @patch("pycalico.datastore.os.getenv", autospec=True)
    @patch("pycalico.datastore.etcd.Client", autospec=True)
    @patch("pycalico.datastore.os.access", autospec=True)
    @patch("pycalico.datastore.os.path.isfile", autospec=True)
    def test_secure_etcd_missing_cert(self, m_isfile, m_access,
                                      m_etcd_client, m_getenv):
        """
        Test validation for secure etcd fails when key is given but cert is
        not.
        """
        m_isfile.return_value = True
        m_access.return_value = True
        etcd_env_dict = {
            ETCD_AUTHORITY_ENV   : "127.0.1.1:2380",
            ETCD_SCHEME_ENV      : "https",
            ETCD_ENDPOINTS_ENV   : "",
            ETCD_KEY_FILE_ENV    : "/path/to/key_file",
            ETCD_CERT_FILE_ENV   : "",
            ETCD_CA_CERT_FILE_ENV: ""
        }

        def m_getenv_return(key, *args):
            return etcd_env_dict[key]
        m_getenv.side_effect = m_getenv_return
        self.etcd_client = Mock(spec=EtcdClient)
        m_etcd_client.return_value = self.etcd_client
        self.assertRaises(DataStoreError, DatastoreClient)
        self.assertFalse(m_etcd_client.called)

    @patch("pycalico.datastore.os.getenv", autospec=True)
    @patch("pycalico.datastore.etcd.Client", autospec=True)
    @patch("pycalico.datastore.os.access", autospec=True)
    @patch("pycalico.datastore.os.path.isfile", autospec=True)
    def test_secure_etcd_missing_key(self, m_isfile, m_access,
                                     m_etcd_client, m_getenv):
        """
        Test validation for secure etcd fails when cert is given but key is
        not.
        """
        m_isfile.return_value = True
        m_access.return_value = True
        etcd_env_dict = {
            ETCD_AUTHORITY_ENV   : "127.0.1.1:2380",
            ETCD_SCHEME_ENV      : "https",
            ETCD_ENDPOINTS_ENV   : "",
            ETCD_KEY_FILE_ENV    : "",
            ETCD_CERT_FILE_ENV   : "/path/to/cert_file",
            ETCD_CA_CERT_FILE_ENV: ""
        }

        def m_getenv_return(key, *args):
            return etcd_env_dict[key]
        m_getenv.side_effect = m_getenv_return
        self.etcd_client = Mock(spec=EtcdClient)
        m_etcd_client.return_value = self.etcd_client
        self.assertRaises(DataStoreError, DatastoreClient)
        self.assertFalse(m_etcd_client.called)

    @patch("pycalico.datastore.os.getenv", autospec=True)
    @patch("pycalico.datastore.etcd.Client", autospec=True)
    @patch("pycalico.datastore.os.access", autospec=True)
    @patch("pycalico.datastore.os.path.isfile", autospec=True)
    def test_secure_etcd_key_not_file(self, m_isfile, m_access,
                                      m_etcd_client, m_getenv):
        """
        Test validation for secure etcd fails when key is not a file.
        """
        m_isfile.return_value = False
        m_access.return_value = True
        etcd_env_dict = {
            ETCD_AUTHORITY_ENV   : "127.0.1.1:2380",
            ETCD_SCHEME_ENV      : "https",
            ETCD_ENDPOINTS_ENV   : "",
            ETCD_KEY_FILE_ENV    : "/path/to/key_dir/",
            ETCD_CERT_FILE_ENV   : "/path/to/cert_file",
            ETCD_CA_CERT_FILE_ENV: "/path/to/ca_file"
        }

        def m_getenv_return(key, *args):
            return etcd_env_dict[key]
        m_getenv.side_effect = m_getenv_return

        self.etcd_client = Mock(spec=EtcdClient)
        m_etcd_client.return_value = self.etcd_client
        self.assertRaises(DataStoreError, DatastoreClient)
        self.assertFalse(m_etcd_client.called)

    @patch("pycalico.datastore.os.getenv", autospec=True)
    @patch("pycalico.datastore.etcd.Client", autospec=True)
    @patch("pycalico.datastore.os.access", autospec=True)
    @patch("pycalico.datastore.os.path.isfile", autospec=True)
    def test_secure_etcd_cert_not_readable(self, m_isfile, m_access,
                                           m_etcd_client, m_getenv):
        """
        Test validation for secure etcd fails when cert is not a readable.
        """
        m_isfile.return_value = True
        m_access.side_effect = [True, False]
        etcd_env_dict = {
            ETCD_AUTHORITY_ENV   : "127.0.1.1:2380",
            ETCD_SCHEME_ENV      : "https",
            ETCD_ENDPOINTS_ENV   : "",
            ETCD_KEY_FILE_ENV    : "/path/to/key_file",
            ETCD_CERT_FILE_ENV   : "/path/to/bad_cert",
            ETCD_CA_CERT_FILE_ENV: "/path/to/ca_file"
        }

        def m_getenv_return(key, *args):
            return etcd_env_dict[key]
        m_getenv.side_effect = m_getenv_return

        self.etcd_client = Mock(spec=EtcdClient)
        m_etcd_client.return_value = self.etcd_client
        self.assertRaises(DataStoreError, DatastoreClient)
        self.assertFalse(m_etcd_client.called)

    @patch("pycalico.datastore.os.getenv", autospec=True)
    @patch("pycalico.datastore.etcd.Client", autospec=True)
    @patch("pycalico.datastore.os.access", autospec=True)
    @patch("pycalico.datastore.os.path.isfile")
    def test_secure_etcd_ca_not_file(self, m_isfile, m_access,
                                     m_etcd_client, m_getenv):
        """
        Test validation for secure etcd fails when ca is not a file.
        """
        m_isfile.side_effect = [True, True, False]
        m_access.return_value = True
        etcd_env_dict = {
            ETCD_AUTHORITY_ENV   : "127.0.1.1:2380",
            ETCD_SCHEME_ENV      : "https",
            ETCD_ENDPOINTS_ENV   : "",
            ETCD_KEY_FILE_ENV    : "/path/to/key_file",
            ETCD_CERT_FILE_ENV   : "/path/to/cert_file",
            ETCD_CA_CERT_FILE_ENV: "/path/to/not_readable"
        }

        def m_getenv_return(key, *args):
            return etcd_env_dict[key]
        m_getenv.side_effect = m_getenv_return

        self.etcd_client = Mock(spec=EtcdClient)
        m_etcd_client.return_value = self.etcd_client
        self.assertRaises(DataStoreError, DatastoreClient)
        self.assertFalse(m_etcd_client.called)


def mock_read_2_peers(path):
    """
    EtcdClient mock side effect for read with 2 IPv4 peers.
    """
    result = Mock(spec=EtcdResult)
    assert_equal(path, BGP_PEERS_PATH)
    children = []
    for ip in ["192.168.3.1", "192.168.5.1"]:
        node = Mock(spec=EtcdResult)
        node.value = "{\"ip\": \"%s\", \"as_num\": \"32245\"}" % ip
        node.key = BGP_PEERS_PATH + str(ip)
        children.append(node)
    result.children = iter(children)
    return result


def mock_read_2_node_peers(path):
    """
    EtcdClient mock side effect for read with 2 IPv4 peers.  Assumes host is
    "TEST_HOST" otherwise raises EtcdKeyNotFound.
    """
    result = Mock(spec=EtcdResult)
    if path != TEST_NODE_BGP_PEERS_PATH:
        raise EtcdKeyNotFound()
    children = []
    for ip in ["192.169.3.1", "192.169.5.1"]:
        node = Mock(spec=EtcdResult)
        node.value = "{\"ip\": \"%s\", \"as_num\": \"32245\"}" % ip
        node.key = TEST_NODE_BGP_PEERS_PATH + str(ip)
        children.append(node)
    result.children = iter(children)
    return result


def mock_read_2_pools(path, recursive=False):
    """
    EtcdClient mock side effect for read with 2 IPv4 pools.
    """
    result = Mock(spec=EtcdResult)
    assert_equal(path, IPV4_POOLS_PATH)
    assert_true(recursive)
    children = []
    for net, ipam in [("192.168.3.0/24", "true"),
                      ("192.168.5.0/24", "false")]:
        node = Mock(spec=EtcdResult)
        node.value = "{\"cidr\": \"%s\",\"ipam\":%s}" % (net, ipam)
        node.key = IPV4_POOLS_PATH + net.replace("/", "-")
        children.append(node)
    result.leaves = iter(children)
    return result


def mock_read_no_pools(path, recursive=False):
    """
    EtcdClient mock side effect for read with no IPv4 pools.
    """
    result = Mock(spec=EtcdResult)
    assert path == IPV4_POOLS_PATH
    assert_true(recursive)
    result.leaves = []
    return result

def mock_read_no_bgppeers(path):
    """
    EtcdClient mock side effect for read with no IPv4 BGP Peers
    """
    result = Mock(spec=EtcdResult)
    assert path == BGP_PEERS_PATH

    # Bug in etcd seems to return the parent when enumerating children if there
    # are no children.  We handle this in the datastore.
    node = Mock(spec=EtcdResult)
    node.value = None
    node.key = BGP_PEERS_PATH
    result.children = iter([node])
    return result


def mock_read_no_node_bgppeers(path):
    """
    EtcdClient mock side effect for read with no IPv4 BGP Peers
    """
    result = Mock(spec=EtcdResult)
    assert path == TEST_NODE_BGP_PEERS_PATH

    # Bug in etcd seems to return the parent when enumerating children if there
    # are no children.  We handle this in the datastore.
    node = Mock(spec=EtcdResult)
    node.value = None
    node.key = TEST_NODE_BGP_PEERS_PATH
    result.children = iter([node])
    return result


def mock_read_2_profiles(path):
    assert path == ALL_PROFILES_PATH
    nodes = [CALICO_V_PATH + "/policy/profile/TEST",
             CALICO_V_PATH + "/policy/profile/UNIT"]
    children = []
    for node in nodes:
        result = Mock(spec=EtcdResult)
        result.key = node
        children.append(result)
    results = Mock(spec=EtcdResult)
    results.children = iter(children)
    return results


def mock_read_no_profiles(path):
    assert path == ALL_PROFILES_PATH
    results = Mock(spec=EtcdResult)
    results.children = iter([])
    return results


def mock_read_profiles_key_error(path):
    assert path == ALL_PROFILES_PATH
    raise EtcdKeyNotFound()


def mock_read_4_endpoints(path, recursive):
    assert path == ALL_ENDPOINTS_PATH
    assert recursive
    leaves = []

    specs = [
        (CALICO_V_PATH + "/host/TEST_HOST/config/marker", "created"),
        (CALICO_V_PATH + "/host/TEST_HOST/workload/docker/1234/endpoint/567890abcdef",
         EP_56.to_json()),
        (CALICO_V_PATH + "/host/TEST_HOST/workload/docker/5678/endpoint/90abcdef1234",
         EP_90.to_json()),
        (CALICO_V_PATH + "/host/TEST_HOST2/config/marker", "created"),
        (CALICO_V_PATH + "/host/TEST_HOST2/workload/docker/1234/endpoint/7890abcdef12",
         EP_78.to_json()),
        (CALICO_V_PATH + "/host/TEST_HOST2/workload/docker/5678/endpoint/1234567890ab",
         EP_12.to_json())]
    for spec in specs:
        leaf = Mock(spec=EtcdResult)
        leaf.key = spec[0]
        leaf.value = spec[1]
        leaves.append(leaf)

    result = Mock(spec=EtcdResult)
    result.leaves = iter(leaves)
    return result


def mock_read_endpoints_key_error(path, recursive):
    assert path == ALL_ENDPOINTS_PATH
    assert recursive
    raise EtcdKeyNotFound()


def mock_read_for_endpoint(ep):
    def mock_read_get_endpoint(path, recursive=None):
        assert recursive
        assert path == TEST_ENDPOINT_PATH
        leaf = Mock(spec=EtcdResult)
        leaf.key = TEST_ENDPOINT_PATH
        leaf.value = ep.to_json()
        result = Mock(spec=EtcdResult)
        result.leaves = iter([leaf])
        return result
    return mock_read_get_endpoint


def get_mock_read_2_ep_for_cont(expected_path, expected_recursive):
    def mock_read(path, recursive=None):
        assert_equal(recursive, expected_recursive)
        assert_equal(path, expected_path)
        leaves = []

        specs = [
            (CALICO_V_PATH + "/host/TEST_HOST/workload/docker/1234/endpoint/1234567890ab",
             EP_12.to_json()),
            (CALICO_V_PATH + "/host/TEST_HOST/workload/docker/1234/endpoint/7890abcdef12",
             EP_78.to_json())
        ]
        for spec in specs:
            leaf = Mock(spec=EtcdResult)
            leaf.key = spec[0]
            leaf.value = spec[1]
            leaves.append(leaf)

        result = Mock(spec=EtcdResult)
        result.leaves = iter(leaves)
        return result
    return mock_read

def mock_read_0_ep_for_cont(path):
    assert path == TEST_CONT_ENDPOINTS_PATH
    leaves = []
    result = Mock(spec=EtcdResult)
    result.leaves = iter(leaves)
    return result
