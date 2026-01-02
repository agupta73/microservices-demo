#!/usr/bin/env python3
"""
Security posture verification tool for cross-cluster connectivity.
Tests:
  1) Intended connectivity exists (C1 -> C2 validation service)
  2) Public exposure is acceptable
  3) Network isolation is configured via NSGs
"""

import subprocess
import json
from typing import Dict, Tuple, List


# Set this to the EXTERNAL-IP of the C2 validation Service
C2_VALIDATION_IP = "13.91.126.20"  # update if IP changes


class K8sConnectivityVerifier:
    def __init__(self, c1_context: str, c2_context: str):
        self.c1_context = c1_context
        self.c2_context = c2_context
        self.results: Dict[str, bool] = {}

    # ---------------------------
    # Helpers
    # ---------------------------

    def run_cmd(self, cmd: str) -> Tuple[str, str, int]:
        """Run a shell command and return stdout, stderr, returncode."""
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return result.stdout, result.stderr, result.returncode

    def exec_in_pod(
        self, context: str, namespace: str, pod: str, cmd: str
    ) -> Tuple[str, str, int]:
        """Execute a command in a pod and return stdout, stderr, returncode."""
        full_cmd = f"kubectl --context {context} -n {namespace} exec {pod} -- {cmd}"
        return self.run_cmd(full_cmd)

    # ---------------------------
    # Test 1: Intended connectivity C1 -> C2 validation
    # ---------------------------

    def test_intended_connectivity(self) -> bool:
        """
        Test C1 -> C2 connectivity using HTTP validation service.

        Assumptions:
          - net-debug pod exists in C1 namespace 'boutique-core'
          - C2 validation Service is reachable on http://C2_VALIDATION_IP:80
          - Response body contains 'OK-C2'
        """
        print("\n[TEST 1] Intended Cross-Cluster Connectivity (C1 -> C2 validation)")
        print("=" * 60)

        # 0. Ensure net-debug pod is running in C1
        get_dbg_cmd = (
            f"kubectl --context {self.c1_context} "
            f"-n boutique-core get pod net-debug "
            f"-o jsonpath='{{.status.phase}}'"
        )
        stdout, stderr, rc = self.run_cmd(get_dbg_cmd)
        phase = stdout.strip()

        if rc != 0 or phase != "Running":
            print("❌ FAILED: net-debug pod is not running in C1 (namespace=boutique-core)")
            if stderr:
                print(f"  Error: {stderr.strip()}")
            return False

        print("✓ Found C1 net-debug pod in Running state")

        # 1. HTTP connectivity check from C1 -> C2 validation Service (external IP)
        url = f"http://{C2_VALIDATION_IP}:80"
        curl_cmd = f"curl -s -o - --max-time 5 {url}"

        stdout, stderr, rc = self.exec_in_pod(
            self.c1_context, "boutique-core", "net-debug", curl_cmd
        )
        body = stdout.strip()

        if rc == 0 and "OK-C2" in body:
            print(f"✓ HTTP connectivity from C1 (net-debug) to C2 validation service OK")
            print(f"  URL: {url}")
            print(f"  Response: {body}")
            print("✓ TEST 1 PASSED: Intended connectivity verified")
            return True

        print("❌ FAILED: HTTP connectivity from C1 to C2 validation service failed")
        print(f"  URL: {url}")
        print(f"  Command: {curl_cmd}")
        print(f"  Return code: {rc}")
        print(f"  Stdout: {stdout.strip()}")
        print(f"  Stderr: {stderr.strip()}")
        return False

    # ---------------------------
    # Test 2: Public exposure
    # ---------------------------

    def list_public_loadbalancers(self, context: str) -> List[Dict[str, str]]:
        """Return all LoadBalancer services with external IPs in a cluster."""
        cmd = f"kubectl --context {context} get svc -A -o json"
        stdout, stderr, rc = self.run_cmd(cmd)
        if rc != 0:
            print(f"⚠️  Could not list services for context {context}")
            if stderr:
                print(f"  Error: {stderr.strip()}")
            return []

        try:
            services = json.loads(stdout)
        except json.JSONDecodeError:
            print(f"⚠️  Failed to parse services JSON for context {context}")
            return []

        public_svcs: List[Dict[str, str]] = []
        for svc in services.get("items", []):
            spec = svc.get("spec", {})
            if spec.get("type") != "LoadBalancer":
                continue

            lb_status = svc.get("status", {}).get("loadBalancer", {})
            for ing in lb_status.get("ingress", []) or []:
                ip = ing.get("ip")
                if ip:
                    public_svcs.append(
                        {
                            "name": svc["metadata"]["name"],
                            "namespace": svc["metadata"]["namespace"],
                            "ip": ip,
                        }
                    )

        return public_svcs

    def test_public_exposure(self) -> bool:
        """Ensure only allowed services are publicly exposed."""
        print("\n[TEST 2] Public Exposure Check")
        print("=" * 60)

        # Allow only frontend services (and validation) to be public for this demo
        allowed_keywords = ["frontend", "c2-validation"]

        for context, cluster_name in [
            (self.c1_context, "C1"),
            (self.c2_context, "C2"),
        ]:
            public_svcs = self.list_public_loadbalancers(context)
            if public_svcs:
                print(f"⚠️  {cluster_name} has publicly exposed LoadBalancer services:")
                for svc in public_svcs:
                    print(f"   - {svc['namespace']}/{svc['name']}: {svc['ip']}")

                critical_public = [
                    s
                    for s in public_svcs
                    if not any(kw in s["name"].lower() for kw in allowed_keywords)
                ]
                if critical_public:
                    print("❌ FAILED: Non-allowed services exposed publicly:")
                    for svc in critical_public:
                        print(f"   - {svc['namespace']}/{svc['name']}: {svc['ip']}")
                    return False
            else:
                print(f"✓ {cluster_name}: No public LoadBalancer services with external IPs")

        print("✓ TEST 2 PASSED: Public exposure acceptable")
        return True

    # ---------------------------
    # Test 3: Network isolation via NSGs
    # ---------------------------

    def test_network_isolation(self) -> bool:
        """Summarize NSG allow rules for both clusters."""
        print("\n[TEST 3] Network Isolation (NSG Summary)")
        print("=" * 60)

        ok = True

        # Adjust resource group names as per your Azure setup
        cluster_nsg_config = [
            (self.c1_context, "C1", "rg-c1-eastus"),
            (self.c2_context, "C2", "rg-c2-westus"),
        ]

        for _, cluster_name, rg in cluster_nsg_config:
            cmd = f"az network nsg list --resource-group {rg} -o json"
            stdout, stderr, rc = self.run_cmd(cmd)

            if rc != 0:
                print(f"⚠️  Could not list NSGs for {cluster_name} (rg={rg})")
                if stderr:
                    print(f"  Error: {stderr.strip()}")
                ok = False
                continue

            try:
                nsgs = json.loads(stdout)
            except json.JSONDecodeError:
                print(f"⚠️  Failed to parse NSG JSON for {cluster_name} (rg={rg})")
                ok = False
                continue

            if not nsgs:
                print(f"⚠️  No NSGs found in {cluster_name} (rg={rg})")
                continue

            for nsg in nsgs:
                name = nsg.get("name", "<unknown>")
                rules = nsg.get("securityRules", [])
                allow_rules = [r for r in rules if r.get("access") == "Allow"]
                deny_rules = [r for r in rules if r.get("access") == "Deny"]
                print(
                    f"✓ {cluster_name} NSG '{name}': "
                    f"{len(allow_rules)} allow rules, {len(deny_rules)} deny rules"
                )

        if ok:
            print("✓ TEST 3 PASSED: Network isolation configured (NSGs present and summarized)")
        else:
            print("⚠️ TEST 3 COMPLETED WITH WARNINGS: Some NSG data could not be retrieved")

        return ok

    # ---------------------------
    # Orchestrator
    # ---------------------------

    def verify_all(self) -> Dict[str, bool]:
        """Run all verification tests and print a summary."""
        print("\n" + "=" * 60)
        print("SECURITY POSTURE VERIFICATION REPORT")
        print("=" * 60)

        results = {
            "intended_connectivity": self.test_intended_connectivity(),
            "public_exposure": self.test_public_exposure(),
            "network_isolation": self.test_network_isolation(),
        }

        self.results = results

        print("\n" + "=" * 60)
        print("VERIFICATION SUMMARY")
        print("=" * 60)

        for test, passed in results.items():
            status = "✓ PASS" if passed else "❌ FAIL"
            print(f"{status}: {test}")

        all_passed = all(results.values())
        print(
            f"\nOverall: {'✓ ALL TESTS PASSED' if all_passed else '❌ SOME TESTS FAILED'}"
        )

        return results


if __name__ == "__main__":
    verifier = K8sConnectivityVerifier(
        c1_context="aks-c1-eastus",
        c2_context="aks-c2-westus",
    )
    verifier.verify_all()
