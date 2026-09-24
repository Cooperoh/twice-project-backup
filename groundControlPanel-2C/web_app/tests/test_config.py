from __future__ import annotations

import pytest

from backend.config import ConfigurationError, load_settings


def test_independent_addresses_allow_sparse_ids_and_shared_ports(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('''[udp]
targets = [
  { id = 24, host = "10.144.1.124", port = 57001 },
  { id = 2, host = "10.144.1.102", port = 57001 },
]
''', encoding="utf-8")
    targets = load_settings(path).udp.targets
    assert [(item.id, item.host, item.port) for item in targets] == [
        (24, "10.144.1.124", 57001),
        (2, "10.144.1.102", 57001),
    ]


@pytest.mark.parametrize("config", [
    'target_host = "10.144.1.100"',
    'target_ports = [57001]',
    'targets = "bad"',
    'targets = [1]',
    'targets = [{id=1, host="127.0.0.1"}]',
    'targets = [{id=0, host="127.0.0.1", port=57001}]',
    'targets = [{id=25, host="127.0.0.1", port=57001}]',
    'targets = [{id=true, host="127.0.0.1", port=57001}]',
    'targets = [{id=1, host="", port=57001}]',
    'targets = [{id=1, host="bad-ip", port=57001}]',
    'targets = [{id=1, host="0.0.0.0", port=57001}]',
    'targets = [{id=1, host="255.255.255.255", port=57001}]',
    'targets = [{id=1, host="127.0.0.1", port=0}]',
    'targets = [{id=1, host="127.0.0.1", port=65536}]',
    'targets = [{id=1, host="127.0.0.1", port=true}]',
    'targets = [{id=1, host="127.0.0.1", port=1}, {id=1, host="127.0.0.2", port=1}]',
    'targets = [{id=1, host="127.0.0.1", port=1}, {id=2, host="127.0.0.1", port=1}]',
])
def test_invalid_or_legacy_target_configuration_fails_at_startup(tmp_path, config):
    path = tmp_path / "config.toml"
    path.write_text("[udp]\n" + config, encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_settings(path)


def test_missing_targets_do_not_create_implicit_destinations(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[udp]\n", encoding="utf-8")
    assert load_settings(path).udp.targets == ()


def test_shipped_configuration_keeps_each_requested_initial_address(config_path):
    targets = load_settings(config_path).udp.targets
    assert [(item.id, item.host, item.port) for item in targets] == [
        (i, "10.144.1.100", 57000 + i) for i in range(1, 25)
    ]
