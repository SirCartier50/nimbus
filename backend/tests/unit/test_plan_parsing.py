from agents.architect import extract_plan


def test_no_plan_block_returns_text_unchanged():
    text = "Sure, here are your S3 buckets: bucket-a, bucket-b."
    display_text, plan = extract_plan(text)
    assert display_text == text
    assert plan is None


def test_extracts_plan_and_strips_tags():
    text = (
        "I'll set up an EC2 instance for you.\n"
        '<nimbus-plan>\n{"explanation": "test", "plan": [{"step": 1, "action": "create"}]}\n</nimbus-plan>'
    )
    display_text, plan = extract_plan(text)
    assert "<nimbus-plan>" not in display_text
    assert "</nimbus-plan>" not in display_text
    assert display_text == "I'll set up an EC2 instance for you."
    assert plan == {"explanation": "test", "plan": [{"step": 1, "action": "create"}]}


def test_preserves_text_after_closing_tag():
    text = "Before.\n<nimbus-plan>\n{\"plan\": []}\n</nimbus-plan>\nAfter."
    display_text, plan = extract_plan(text)
    assert display_text == "Before.\nAfter."
    assert plan == {"plan": []}


def test_malformed_json_inside_tags_falls_back_to_raw_text():
    text = "Explanation.\n<nimbus-plan>\n{not valid json\n</nimbus-plan>"
    display_text, plan = extract_plan(text)
    assert plan is None
    assert display_text == text


def test_only_opening_tag_present_is_treated_as_no_plan():
    text = "Some text <nimbus-plan> but no closing tag"
    display_text, plan = extract_plan(text)
    assert plan is None
    assert display_text == text


def test_hash_comments_inside_plan_json_are_stripped_and_parsed():
    # Reproduces a real model output: inline "#" comments after config values,
    # which is valid Python/YAML but not valid JSON.
    text = (
        "Here's the plan.\n<nimbus-plan>\n"
        "{\n"
        '"explanation": "test",\n'
        '"plan": [{"step": 1, "action": "create", "resource_type": "ec2_instance", "config": {\n'
        '"ImageId": "ami-0c55b159cbfafe1f0", # Amazon Linux 2 (us-east-1)\n'
        '"KeyName": "nimbus-k3s-test-key", # Auto-generated key pair\n'
        '"SecurityGroupIds": ["default"] # SSH-only initially\n'
        "}}]\n"
        "}\n</nimbus-plan>"
    )
    display_text, plan = extract_plan(text)
    assert display_text == "Here's the plan."
    assert plan["explanation"] == "test"
    config = plan["plan"][0]["config"]
    assert config["ImageId"] == "ami-0c55b159cbfafe1f0"
    assert config["KeyName"] == "nimbus-k3s-test-key"
    assert config["SecurityGroupIds"] == ["default"]


def test_slash_comment_and_trailing_comma_are_stripped():
    text = (
        "<nimbus-plan>\n"
        '{"explanation": "test", "plan": [], "cost_warning": "none", } // trailing note\n'
        "</nimbus-plan>"
    )
    display_text, plan = extract_plan(text)
    assert plan == {"explanation": "test", "plan": [], "cost_warning": "none"}


def test_hash_inside_string_value_is_preserved_not_stripped():
    text = (
        "<nimbus-plan>\n"
        '{"explanation": "Bucket key is reports#2026.csv", "plan": []}\n'
        "</nimbus-plan>"
    )
    _, plan = extract_plan(text)
    assert plan["explanation"] == "Bucket key is reports#2026.csv"


def test_still_falls_back_to_raw_text_when_unparseable_even_after_stripping():
    text = "Explanation.\n<nimbus-plan>\n{not valid json # comment\n</nimbus-plan>"
    display_text, plan = extract_plan(text)
    assert plan is None
    assert display_text == text
