import sys
import unittest
from unittest.mock import Mock, patch

import connector


class ConnectorLauncherTests(unittest.TestCase):
    def test_server_binds_before_pairing_secret_is_issued(self):
        events = []
        broker = Mock()
        broker.issue_pairing_secret.side_effect = lambda: events.append("secret") or "pairing-secret"
        server = Mock()
        server.serve_forever.side_effect = KeyboardInterrupt

        def build_server(*_args, **_kwargs):
            events.append("bind")
            return server

        with (
            patch.object(connector, "create_connector_app", return_value=(Mock(), broker)),
            patch.object(connector, "ExclusiveThreadedWSGIServer", side_effect=build_server),
            patch.object(sys, "argv", ["connector.py", "--no-open"]),
        ):
            connector.main()

        self.assertEqual(events, ["bind", "secret"])
        server.server_close.assert_called_once_with()

    def test_occupied_port_never_issues_or_opens_pairing_link(self):
        broker = Mock()
        with (
            patch.object(connector, "create_connector_app", return_value=(Mock(), broker)),
            patch.object(connector, "ExclusiveThreadedWSGIServer", side_effect=SystemExit(1)),
            patch.object(connector.webbrowser, "open") as open_browser,
            patch.object(sys, "argv", ["connector.py"]),
        ):
            with self.assertRaises(SystemExit):
                connector.main()

        broker.issue_pairing_secret.assert_not_called()
        open_browser.assert_not_called()

    def test_windows_connector_disables_address_reuse(self):
        self.assertFalse(connector.ExclusiveThreadedWSGIServer.allow_reuse_address)


if __name__ == "__main__":
    unittest.main()
