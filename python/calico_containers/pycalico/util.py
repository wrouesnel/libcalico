from netaddr.core import AddrFormatError

import netaddr
import socket
import sys
import os
import re
import logging
from netaddr import IPNetwork, IPAddress
from subprocess import check_output, CalledProcessError

_log = logging.getLogger(__name__)
_log.addHandler(logging.NullHandler())

HOSTNAME_ENV = "HOSTNAME"

"""
Compile Regexes
"""
# Splits into groups that start w/ no whitespace and contain all lines below
# that start w/ whitespace
INTERFACE_SPLIT_RE = re.compile(r'(\d+:.*(?:\n\s+.*)+)')
# Grabs interface name
IFACE_RE = re.compile(r'^\d+: (\S+):')
# Grabs v4 addresses
IPV4_RE = re.compile(r'inet ((?:\d+\.){3}\d+)/\d+')
# Grabs v6 addresses
IPV6_RE = re.compile(r'inet6 ([a-fA-F\d:]+)/\d{1,3}')


def generate_cali_interface_name(prefix, ep_id):
    """Helper method to generate a name for a calico veth, given the endpoint
    ID

    This takes a prefix, and then truncates the EP ID.

    :param prefix: T
    :param ep_id:
    :return:
    """
    if len(prefix) > 4:
        raise ValueError('Prefix must be 4 characters or less.')
    return prefix + ep_id[:11]


def get_host_ips(version=4, exclude=None):
    """
    Gets all IP addresses assigned to this host.

    Ignores Loopback Addresses

    This function is fail-safe and will return an empty array instead of
    raising any exceptions.

    :param version: Desired IP address version. Can be 4 or 6. defaults to 4
    :param exclude: list of interface name regular expressions to ignore
                    (ex. ["^lo$","docker0.*"])
    :return: List of IPAddress objects.
    """
    exclude = exclude or []
    ip_addrs = []

    # Select Regex for IPv6 or IPv4.
    ip_re = IPV4_RE if version is 4 else IPV6_RE

    # Call `ip addr`.
    try:
        ip_addr_output = check_output(["ip", "-%d" % version, "addr"])
    except (CalledProcessError, OSError):
        print "Call to 'ip addr' Failed"
        sys.exit(1)

    # Separate interface blocks from ip addr output and iterate.
    for iface_block in INTERFACE_SPLIT_RE.findall(ip_addr_output):
        # Try to get the interface name from the block
        match = IFACE_RE.match(iface_block)
        iface = match.group(1)
        # Ignore the interface if it is explicitly excluded
        if match and not any(re.match(regex, iface) for regex in exclude):
            # Iterate through Addresses on interface.
            for address in ip_re.findall(iface_block):
                # Append non-loopback addresses.
                if not IPNetwork(address).ip.is_loopback():
                    ip_addrs.append(IPAddress(address))

    return ip_addrs


def get_hostname():
    """
    This will be the hostname returned by socket.gethostname,
    but can be overridden by passing in the $HOSTNAME environment variable.
    Though most shells appear to have $HOSTNAME set, it is actually not
    passed into subshells, so calicoctl will not see a set $HOSTNAME unless
    the user has explicitly set it in their environment, thus defaulting
    this function to return socket.gethostname.
    :return: String representation of the hostname.
    """
    try:
        return os.environ[HOSTNAME_ENV]
    except KeyError:
        # The user does not have a set $HOSTNAME. Since this is a common
        # scenario, return socket.gethostname instead of just erroring.
        return socket.gethostname()


def validate_port_str(port_str):
    """
    Checks whether the command line word specifying a set of ports is valid.
    """
    return validate_ports(port_str.split(","))


def validate_ports(port_list):
    """
    Checks whether a list of ports are within range of 0 and 65535.
    The port list must include a number or a number range.

    A valid number range must be two numbers delimited by a colon with the
    second number higher than the first. Both numbers must be within range.
    If a number range is invalid, the function will return False.

    :param port_list:
    :return: a Boolean: True if in range, False if not in range
    """
    in_range = True
    for port in port_list:
        if ":" in str(port):
            ports = port.split(":")
            in_range = (len(ports) == 2) and (int(ports[0]) < int(ports[1])) \
                       and validate_ports(ports)
        else:
            try:
                in_range = 0 <= int(port) < 65536
            except ValueError:
                in_range = False
        if not in_range:
            break

    return in_range


def validate_characters(input_string):
    """
    Validate that characters in string are supported by Felix.
    Felix supports letters a-z, numbers 0-9, and symbols _.-

    :param input_string: string to be validated
    :return: Boolean: True if valid, False if invalid
    """
    # List of valid characters that Felix permits
    valid_chars = '[a-zA-Z0-9_\.\-]'

    # Check for invalid characters
    if not re.match("^%s+$" % valid_chars, input_string):
        return False
    else:
        return True


def validate_icmp_type(icmp_type):
    """
    Validate that icmp_type is an integer between 0 and 255.
    If not return False.

    :param icmp_type: int value representing an icmp type
    :return: Boolean: True if valid icmp type, False if not
    """
    try:
        valid = 0 <= int(icmp_type) < 255
    except ValueError:
        valid = False
    return valid


def validate_hostname_port(hostname_port):
    """
    Validate the hostname and port format.  (<HOSTNAME>:<PORT>)
    An IPv4 address is a valid hostname.

    :param hostname_port: The string to verify
    :return: Boolean: True if valid, False if invalid
    """
    # Should contain a single ":" separating hostname and port
    if not isinstance(hostname_port, str):
        _log.error("Must provide string for hostname:port validation, not: %s"
                   % type(hostname_port))
        return False

    try:
        (hostname, port) = hostname_port.split(":")
    except ValueError:
        _log.error("Must provide a string splittable by ':' for hostname-port.")
        return False

    # Check the hostname format.
    if not validate_hostname(hostname):
        return False

    # Check port range.
    try:
        port = int(port)
    except ValueError:
        _log.error("Port must be an integer.")
        return False
    if port < 1 or port > 65535:
        _log.error("Provided port (%d) must be between 1 and 65535." % port)
        return False
    return True


def validate_hostname(hostname):
    """
    Validate a hostname string.  This allows standard hostnames and IPv4
    addresses.

    :param hostname: The hostname to validate.
    :return: Boolean: True if valid, False if invalid
    """
    # Hostname length is limited.
    if not isinstance(hostname, str):
        _log.error("Hostname must be a string, not %s" % type(hostname))
        return False
    hostname_len = len(hostname)
    if hostname_len > 255:
        _log.error("Hostname length (%d) should be less than 255 characters."
                   % hostname_len)
        return False

    # Hostname labels may consist of numbers, letters and hyphens, but may not
    # end or begin with a hyphen.
    allowed = re.compile("(?!-)[a-z\d-]{1,63}(?<!-)$", re.IGNORECASE)
    if not all(allowed.match(x) for x in hostname.split(".")):
        _log.error("Hostname label may only consist of numbers, letters, and "
                   "hyphens (but may not end or begin with a hyphen.")
        return False
    return True


def validate_asn(asn):
    """
    Validate the format of a 2-byte or 4-byte autonomous system number

    :param asn: User input of AS number
    :return: Boolean: True if valid format, False if invalid format
    """
    try:
        if "." in str(asn):
            left_asn, right_asn = str(asn).split(".")
            asn_ok = (0 <= int(left_asn) <= 65535) and \
                     (0 <= int(right_asn) <= 65535)
        else:
            asn_ok = 0 <= int(asn) <= 4294967295
    except ValueError:
        asn_ok = False

    return asn_ok


def validate_cidr(cidr):
    """
    Validate cidr is in correct CIDR notation

    :param cidr: IP addr and associated routing prefix
    :return: Boolean: True if valid IP, False if invalid
    """
    try:
        netaddr.IPNetwork(cidr)
        return True
    except (AddrFormatError, ValueError):
        # Some versions of Netaddr have a bug causing them to return a
        # ValueError rather than an AddrFormatError, so catch both.
        return False


def validate_cidr_versions(cidrs, ip_version=None):
    """
    Validate CIDR versions match each other and (if specified) the given IP
    version.

    :param cidrs: List of CIDRs whose versions need verification
    :param ip_version: Expected IP version that CIDRs should use (4, 6, None)
                       If None, CIDRs should all have same IP version
    :return: Boolean: True if versions match each other and ip_version,
                      False otherwise
    """
    try:
        for cidr in cidrs:
            network = netaddr.IPNetwork(cidr)
            if ip_version is None:
                ip_version = network.version
            elif ip_version != network.version:
                return False
    except (AddrFormatError, ValueError):
        # Some versions of Netaddr have a bug causing them to return a
        # ValueError rather than an AddrFormatError, so catch both.
        return False
    return True


def validate_ip(ip_addr, version):
    """
    Validate that ip_addr is a valid IPv4 or IPv6 address

    :param ip_addr: IP address to be validated
    :param version: 4 or 6
    :return: Boolean: True if valid, False if invalid.
    """
    assert version in (4, 6)

    if version == 4:
        return netaddr.valid_ipv4(ip_addr)
    if version == 6:
        return netaddr.valid_ipv6(ip_addr)
