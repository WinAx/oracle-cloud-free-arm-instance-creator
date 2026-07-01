import unittest
from unittest.mock import patch

from a1_hammer import extract_message, is_permanent_error, throttle_delay, was_created


class ResponseParsingTests(unittest.TestCase):
    def test_extracts_oci_error_message(self) -> None:
        response = '{"code":"LimitExceeded","message":"Service limits were exceeded"}'
        self.assertEqual(extract_message(response), "Service limits were exceeded")

    def test_recognizes_created_instance(self) -> None:
        response = '{"data":{"id":"ocid1.instance.example","lifecycle-state":"PROVISIONING"}}'
        created, instance_id, state = was_created(response)
        self.assertTrue(created)
        self.assertEqual(instance_id, "ocid1.instance.example")
        self.assertEqual(state, "PROVISIONING")


class ErrorPolicyTests(unittest.TestCase):
    def test_service_limit_error_is_permanent(self) -> None:
        self.assertTrue(is_permanent_error("The following service limits were exceeded: standard-a1-core-count"))

    def test_capacity_error_is_retryable(self) -> None:
        self.assertFalse(is_permanent_error("Out of host capacity."))

    def test_rate_limit_uses_backoff(self) -> None:
        with patch("a1_hammer.random.uniform", return_value=0):
            self.assertEqual(throttle_delay("Too many requests for the user", 120, 1800, 0), 120)
            self.assertEqual(throttle_delay("Too many requests for the user", 120, 1800, 1), 240)


if __name__ == "__main__":
    unittest.main()
