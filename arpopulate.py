from argparse import ArgumentParser
from datetime import datetime
from ipaddress import ip_network, IPv4Network, IPv6Network, IPv4Address, IPv6Address
from random import randrange
from re import search, split
from sys import stderr
from time import sleep
from typing import Iterable, Dict

try:
    from scapy.sendrecv import srp
    from scapy.layers.inet import Ether
    from scapy.layers.l2 import ARP
except ModuleNotFoundError:
    print(
        "Did you install the scapy module? See https://pypi.org/project/scapy/",
        file=stderr,
    )
    raise


class MAC(int):
    @classmethod
    def parse(cls, mac: str):
        return MAC.from_bytes(
            [int(part, 16) for part in split(r"[^0-9a-fA-F]", mac)],
            byteorder="big",
            signed=False,
        )

    def __str__(self) -> str:
        return ":".join(
            [
                format(part, "x")
                for part in self.to_bytes(byteorder="big", signed=False, length=6)
            ]
        )

    def __add__(self, other):
        return MAC(super().__add__(other))

    def __sub__(self, other):
        return MAC(super().__sub__(other))

    def __and__(self, other):
        return MAC(super().__and__(other))


class MACRange(object):
    def __init__(self, mac):
        matches = search(
            r"^(?P<mac>(?:[0-9a-fA-F]{2}[:.-]){5}[0-9a-fA-F]{2})(/(?P<mask>\d+))?$", mac
        )
        self.mask = int(matches.group("mask"))
        self.mac = MAC.parse(matches.group("mac"))
        self.mac &= ~((1 << (48 - self.mask)) - 1)

    def __len__(self):
        return 1 << (48 - self.mask)


class MACRanges(list, Iterable[MACRange]):
    def rand(self):
        offset = randrange(0, self.len())
        for macs in self:
            if offset >= len(macs):
                offset -= len(macs)
            else:
                return macs.mac + offset

    def len(self) -> int:
        return sum([len(macs) for macs in self])


class IPNetworks(list, Iterable[IPv4Network | IPv6Network]):
    def subnets_of(self, others: Iterable[IPv4Network | IPv6Network]) -> bool:
        for s in self:
            for o in others:
                if s.subnet_of(o):
                    return True
        return False

    def addresses_exclude(self, others: Iterable[IPv4Network | IPv6Network]):
        while self.subnets_of(others):
            for s in self:
                for o in others:
                    if o.subnet_of(s):
                        self.remove(s)
                        self.extend(s.address_exclude(o))
                    elif s.subnet_of(o):
                        self.remove(s)

    def rand(self):
        offset = randrange(0, self.len())
        for network in self:
            if offset >= network.num_addresses:
                offset -= network.num_addresses
            else:
                return network.network_address + offset

    def len(self) -> int:
        return sum([network.num_addresses for network in self])


def spoof(dst: IPv4Address | IPv6Address, src: IPv4Address | IPv6Address, hwsrc: MAC):
    srp(
        Ether(dst="ff:ff:ff:ff:ff:ff")
        / ARP(pdst=str(dst), psrc=str(src), hwsrc=str(hwsrc)),
        timeout=0,
        verbose=False,
    )


if __name__ == "__main__":
    parser = ArgumentParser(
        description="ARPopulate is a simple utility to populate remote ARP tables "
        "(e.g. to populate honeypot networks)."
    )
    parser.add_argument(
        "--target",
        type=str,
        action="append",
        required=True,
        help="Network ranges to target with ARP spoofing",
    )
    parser.add_argument(
        "--spoof",
        type=str,
        action="append",
        required=True,
        help="Network ranges to spoof",
    )
    parser.add_argument(
        "--mac",
        type=str,
        action="append",
        required=True,
        help="MAC address ranges to spoof",
    )
    parser.add_argument(
        "--count",
        type=float,
        default=10,
        help="The number of entries to spoof (defaults to 10)",
    )
    parser.add_argument(
        "--seconds",
        type=int,
        metavar="N",
        help="Repeat the spoofing every N seconds (default does not repeat)",
    )
    args = parser.parse_args()

    # Exclude targets from the spoof-able addresses
    targets = IPNetworks([ip_network(network) for network in args.target])
    spoofs = IPNetworks([ip_network(network) for network in args.spoof])
    spoofs.addresses_exclude(targets)
    spoof_macs = MACRanges([MACRange(spoof_mac) for spoof_mac in args.mac])

    # Build a spoof table
    spoofed: Dict[IPv4Address | IPv6Address, MAC] = {}

    for _ in range(min(args.count, spoofs.len())):
        address = spoofs.rand()
        spoofs.addresses_exclude([ip_network(address)])
        spoofed[address] = spoof_macs.rand()

    while True:
        for address, mac in spoofed.items():
            for target in targets:
                for host in target.hosts():
                    print(
                        f"{datetime.now()} Spoofing {address} as {mac} against {host}"
                    )
                    spoof(host, address, mac)

        if args.seconds:
            print(f"{datetime.now()} Sleeping {args.seconds} seconds...")
            sleep(args.seconds)
        else:
            break
