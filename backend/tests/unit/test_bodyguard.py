from unittest.mock import MagicMock, patch

from agents import bodyguard


def test_fresh_patrol_buffer_shape():
    assert bodyguard._new_patrol_buffer() == {
        "instances_stopped": 0,
        "logs": [],
        "alerts": [],
        "sub_resources": {"volumes": [], "elastic_ips": [], "snapshots": []},
    }


def test_log_and_alert_write_only_to_their_buffer():
    buf_a = bodyguard._new_patrol_buffer()
    buf_b = bodyguard._new_patrol_buffer()

    bodyguard._log(buf_a, "A did something")
    bodyguard._alert(buf_a, "A alert", "warning")

    assert buf_a["logs"] and not buf_b["logs"]
    assert buf_a["alerts"] and not buf_b["alerts"]
    assert buf_a["alerts"][0]["severity"] == "warning"
    assert buf_a["alerts"][0]["timestamp"]  # persisted verbatim later — must exist


# ── Deterministic patrol ────────────────────────────────────────────────────
# The patrol is plain code — no LLM. (The old LLM-driven patrol burned a Bedrock
# tool-loop per user every 5 minutes, which surfaced as a surprise AWS bill.)


def _instance(instance_id="i-1", instance_type="m5.xlarge"):
    return {
        "InstanceId": instance_id,
        "InstanceType": instance_type,
        "State": {"Name": "running"},
        "Tags": [],
    }


def _aws_mocks(instances=(), datapoints=()):
    ec2 = MagicMock()
    ec2.describe_instances.return_value = {"Reservations": [{"Instances": list(instances)}]}
    ec2.describe_volumes.return_value = {"Volumes": []}
    ec2.describe_addresses.return_value = {"Addresses": []}
    ec2.describe_snapshots.return_value = {"Snapshots": []}
    cw = MagicMock()
    cw.get_metric_statistics.return_value = {"Datapoints": [{"Average": d} for d in datapoints]}
    sts = MagicMock()
    sts.get_caller_identity.return_value = {"Account": "123"}
    return ec2, cw, sts


def test_patrol_uses_no_llm_at_all():
    # The module must not even import a tool loop — cost regression guard.
    assert not hasattr(bodyguard, "run_tool_loop")
    assert not hasattr(bodyguard, "BODYGUARD_PROMPT")


def test_patrol_stops_idle_instance_and_alerts_first():
    buffer = bodyguard._new_patrol_buffer()
    ec2, cw, sts = _aws_mocks(instances=[_instance()], datapoints=[1.0, 2.0, 3.0])

    with patch("agents.bodyguard.get_ec2_client", return_value=ec2), \
         patch("agents.bodyguard.get_cloudwatch_client", return_value=cw), \
         patch("agents.bodyguard.get_sts_client", return_value=sts):
        bodyguard._run_patrol(MagicMock(), buffer)

    ec2.stop_instances.assert_called_once_with(InstanceIds=["i-1"])
    assert buffer["instances_stopped"] == 1
    assert any("Stopping idle instance" in a["message"] for a in buffer["alerts"])
    assert any("Non-free-tier" in a["message"] for a in buffer["alerts"])


def test_patrol_leaves_busy_instance_running():
    buffer = bodyguard._new_patrol_buffer()
    ec2, cw, sts = _aws_mocks(instances=[_instance()], datapoints=[60.0, 70.0, 80.0])

    with patch("agents.bodyguard.get_ec2_client", return_value=ec2), \
         patch("agents.bodyguard.get_cloudwatch_client", return_value=cw), \
         patch("agents.bodyguard.get_sts_client", return_value=sts):
        bodyguard._run_patrol(MagicMock(), buffer)

    ec2.stop_instances.assert_not_called()
    assert buffer["instances_stopped"] == 0


def test_patrol_never_stops_instance_without_cpu_data():
    # New instances have no datapoints yet — logged, never touched.
    buffer = bodyguard._new_patrol_buffer()
    ec2, cw, sts = _aws_mocks(instances=[_instance(instance_type="t2.micro")], datapoints=[])

    with patch("agents.bodyguard.get_ec2_client", return_value=ec2), \
         patch("agents.bodyguard.get_cloudwatch_client", return_value=cw), \
         patch("agents.bodyguard.get_sts_client", return_value=sts):
        bodyguard._run_patrol(MagicMock(), buffer)

    ec2.stop_instances.assert_not_called()
    assert any("no CPU data yet" in e["message"] for e in buffer["logs"])


def test_patrol_requires_min_datapoints_before_stopping():
    # Below-threshold CPU but only 2 datapoints — conservative, don't stop.
    buffer = bodyguard._new_patrol_buffer()
    ec2, cw, sts = _aws_mocks(instances=[_instance()], datapoints=[1.0, 2.0])

    with patch("agents.bodyguard.get_ec2_client", return_value=ec2), \
         patch("agents.bodyguard.get_cloudwatch_client", return_value=cw), \
         patch("agents.bodyguard.get_sts_client", return_value=sts):
        bodyguard._run_patrol(MagicMock(), buffer)

    ec2.stop_instances.assert_not_called()


def test_patrol_alerts_on_orphaned_volumes():
    buffer = bodyguard._new_patrol_buffer()
    ec2, cw, sts = _aws_mocks()
    ec2.describe_volumes.return_value = {
        "Volumes": [{"VolumeId": "vol-1", "Size": 100, "VolumeType": "gp3", "State": "available", "Attachments": []}]
    }

    with patch("agents.bodyguard.get_ec2_client", return_value=ec2), \
         patch("agents.bodyguard.get_cloudwatch_client", return_value=cw), \
         patch("agents.bodyguard.get_sts_client", return_value=sts):
        bodyguard._run_patrol(MagicMock(), buffer)

    assert any("orphaned EBS volume" in a["message"] for a in buffer["alerts"])
    assert buffer["sub_resources"]["volumes"][0]["volume_id"] == "vol-1"
