import argparse
import json
import logging
import os
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("BACKEND_BASE_URL", "https://www.balisongflippingcenter.com/api")

import boto3  # noqa: E402
import fakeredis  # noqa: E402
import yaml  # noqa: E402

from app import bedrock_client, sessions  # noqa: E402
from app.config import settings  # noqa: E402
from app.tools import execute_tool  # noqa: E402

EVALS_DIR = Path(__file__).parent
# Sonnet 4.6 is the strongest model this AWS account has Bedrock access to.
JUDGE_MODEL_ID = "us.anthropic.claude-sonnet-4-6"
# USD per million (input, output) tokens at Anthropic list price -- Bedrock on-demand rates may differ.
LATCH_PRICING = (1.00, 5.00)
JUDGE_PRICING = (3.00, 15.00)
# Prompt-cache reads bill at 0.1x the input price and 5-minute cache writes at 1.25x.
CACHE_READ_MULTIPLIER = 0.1
CACHE_WRITE_MULTIPLIER = 1.25
EVAL_ACCESS_TOKEN = "Bearer eval-token"
FAKE_REPORT_RESULT = {"id": 0, "status": "PENDING", "note": "eval stub -- no report was filed"}
MAX_JUDGE_RESULT_CHARS = 1500

JUDGE_SYSTEM = """You grade replies from Latch, the AI assistant for Balisong Flipping Center, a community \
site for balisong (butterfly knife) flippers. You are given a conversation, every tool call Latch made with \
the result it got back, and a rubric. Decide whether Latch's final reply satisfies the rubric. Judge only \
against the rubric and the tool results shown -- not your own knowledge of knives or the site. Record your \
verdict with the record_verdict tool."""

VERDICT_TOOL = {
    "toolSpec": {
        "name": "record_verdict",
        "description": "Record whether the final reply satisfies the rubric.",
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "pass": {"type": "boolean"},
                    "reason": {"type": "string", "description": "One sentence explaining the verdict"},
                },
                "required": ["pass", "reason"],
            }
        },
    }
}


class UsageRecorder(logging.Handler):
    def __init__(self):
        super().__init__()
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_read_tokens = 0
        self.cache_write_tokens = 0

    def emit(self, record):
        if record.msg.startswith("bedrock usage"):
            input_tokens, output_tokens, cache_read_tokens, cache_write_tokens = record.args
            self.input_tokens += input_tokens or 0
            self.output_tokens += output_tokens or 0
            self.cache_read_tokens += cache_read_tokens or 0
            self.cache_write_tokens += cache_write_tokens or 0


def recording_execute_tool(calls: list[dict]):
    # Without a token, execute_tool rejects report_content itself before any backend call, so only the
    # logged-in path needs stubbing to keep evals from filing real reports.
    def run(name, tool_input, access_token=None):
        if name == "report_content" and access_token:
            result = FAKE_REPORT_RESULT
        else:
            result = execute_tool(name, tool_input, access_token)
        calls.append({"name": name, "input": tool_input, "result": result})
        return result

    return run


def run_case(case: dict) -> dict:
    session_id = f"eval-{uuid.uuid4()}"
    access_token = EVAL_ACCESS_TOKEN if case.get("logged_in") else None
    usage = UsageRecorder()
    logging.getLogger("app.bedrock_client").addHandler(usage)
    turns = []
    start = time.monotonic()
    try:
        for message in case["messages"]:
            calls = []
            with patch("app.bedrock_client.execute_tool", recording_execute_tool(calls)):
                reply = "".join(bedrock_client.stream_chat(session_id, message, access_token, case.get("current_path")))
            turns.append({"message": message, "reply": reply, "tool_calls": calls})
    finally:
        logging.getLogger("app.bedrock_client").removeHandler(usage)
    return {
        "turns": turns,
        "latency_seconds": time.monotonic() - start,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_read_tokens": usage.cache_read_tokens,
        "cache_write_tokens": usage.cache_write_tokens,
    }


def tool_error(result: dict) -> str | None:
    inner = result["results"] if isinstance(result.get("results"), dict) else result
    if "error" in inner:
        return str(inner.get("status_code", inner["error"]))
    return None


def check(case: dict, run: dict) -> list[str]:
    expect = case.get("expect", {})
    last = run["turns"][-1]
    calls = last["tool_calls"]
    called = [call["name"] for call in calls]
    reply = last["reply"].lower()
    failures = []

    for name in expect.get("tools", []):
        if name not in called:
            failures.append(f"expected {name} to be called")
    for name in expect.get("forbid_tools", []):
        if name in called:
            failures.append(f"{name} should not have been called")
    for name, args in expect.get("tool_args", {}).items():
        for arg, needle in args.items():
            if not any(
                call["name"] == name and str(needle).lower() in str(call["input"].get(arg, "")).lower()
                for call in calls
            ):
                failures.append(f"no {name} call with {arg} containing {needle!r}")
    if expect.get("no_tool_errors", True):
        for call in calls:
            error = tool_error(call["result"])
            if error:
                failures.append(f"{call['name']}({json.dumps(call['input'])}) returned error {error}")
    for text in expect.get("contains", []):
        if text.lower() not in reply:
            failures.append(f"reply missing {text!r}")
    if expect.get("contains_any") and not any(text.lower() in reply for text in expect["contains_any"]):
        failures.append(f"reply contains none of {expect['contains_any']}")
    for text in expect.get("not_contains", []):
        if text.lower() in reply:
            failures.append(f"reply should not contain {text!r}")
    return failures


def format_transcript(case: dict, run: dict) -> str:
    lines = [f"User logged in: {'yes' if case.get('logged_in') else 'no'}"]
    lines.append(f"User's current page: {case.get('current_path') or 'unknown'}")
    for turn in run["turns"]:
        lines.append(f"\nUSER: {turn['message']}")
        for call in turn["tool_calls"]:
            result = json.dumps(call["result"])[:MAX_JUDGE_RESULT_CHARS]
            lines.append(f"TOOL CALL {call['name']}({json.dumps(call['input'])}) -> {result}")
        lines.append(f"LATCH: {turn['reply']}")
    return "\n".join(lines)


def judge(case: dict, run: dict, client) -> tuple[str | None, int, int]:
    prompt = f"{format_transcript(case, run)}\n\nRubric for Latch's final reply:\n{case['expect']['judge']}"
    response = client.converse(
        modelId=JUDGE_MODEL_ID,
        system=[{"text": JUDGE_SYSTEM}],
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        toolConfig={"tools": [VERDICT_TOOL], "toolChoice": {"tool": {"name": "record_verdict"}}},
        inferenceConfig={"maxTokens": 1024},
    )
    usage = response["usage"]
    verdict = next(block["toolUse"]["input"] for block in response["output"]["message"]["content"] if "toolUse" in block)
    failure = None if verdict["pass"] else f"judge: {verdict['reason']}"
    return failure, usage["inputTokens"], usage["outputTokens"]


def cost(input_tokens: int, output_tokens: int, pricing: tuple[float, float], cache_read_tokens: int = 0, cache_write_tokens: int = 0) -> float:
    billed_input = input_tokens + cache_read_tokens * CACHE_READ_MULTIPLIER + cache_write_tokens * CACHE_WRITE_MULTIPLIER
    return (billed_input * pricing[0] + output_tokens * pricing[1]) / 1_000_000


def write_report(results: list[dict], runs_per_case: int, totals: dict) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    reports_dir = EVALS_DIR / "reports"
    reports_dir.mkdir(exist_ok=True)

    passed_runs = sum(result["passed"] for result in results)
    total_runs = sum(result["runs"] for result in results)
    by_category = defaultdict(lambda: [0, 0])
    for result in results:
        by_category[result["category"]][0] += result["passed"]
        by_category[result["category"]][1] += result["runs"]

    latch_cost = cost(
        totals["latch_input"], totals["latch_output"], LATCH_PRICING, totals["latch_cache_read"], totals["latch_cache_write"]
    )
    judge_cost = cost(totals["judge_input"], totals["judge_output"], JUDGE_PRICING)
    lines = [
        f"# Latch eval report -- {timestamp}",
        "",
        f"- **Pass rate:** {passed_runs}/{total_runs} runs ({passed_runs / total_runs:.0%})",
        f"- **Cases:** {len(results)} x {runs_per_case} runs",
        f"- **Latch model:** `{settings.bedrock_model_id}` -- judge: `{JUDGE_MODEL_ID}`",
        f"- **Latch tokens:** {totals['latch_input']:,} in / {totals['latch_output']:,} out "
        f"+ {totals['latch_cache_read']:,} cache read / {totals['latch_cache_write']:,} cache write",
        f"- **Avg latency per case run:** {totals['latency'] / total_runs:.1f}s",
        f"- **Estimated cost (list price):** ${latch_cost:.3f} Latch + ${judge_cost:.3f} judge "
        f"= ${latch_cost + judge_cost:.3f}",
        "",
        "## By category",
        "",
        "| Category | Passed | Rate |",
        "|---|---|---|",
    ]
    for category, (passed, runs) in sorted(by_category.items()):
        lines.append(f"| {category} | {passed}/{runs} | {passed / runs:.0%} |")
    lines += ["", "## By case", "", "| Case | Category | Passed | Failures |", "|---|---|---|---|"]
    for result in results:
        failures = "<br>".join(sorted(set(result["failures"]))).replace("|", "\\|") or "--"
        lines.append(f"| {result['id']} | {result['category']} | {result['passed']}/{result['runs']} | {failures} |")

    report_path = reports_dir / f"{timestamp}.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (reports_dir / f"{timestamp}.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return report_path


def main():
    parser = argparse.ArgumentParser(description="Run Latch's eval suite against the real model.")
    parser.add_argument("--runs", type=int, default=3, help="Runs per case (default 3)")
    parser.add_argument("--case", help="Only run cases whose id contains this string")
    args = parser.parse_args()

    sessions._client = fakeredis.FakeRedis(decode_responses=True)
    logging.getLogger("app.bedrock_client").setLevel(logging.INFO)
    judge_client = boto3.client("bedrock-runtime", region_name=settings.aws_region)
    cases = yaml.safe_load((EVALS_DIR / "cases.yaml").read_text(encoding="utf-8"))
    if args.case:
        cases = [case for case in cases if args.case in case["id"]]

    totals = defaultdict(int)
    results = []
    for case in cases:
        result = {"id": case["id"], "category": case["category"], "runs": args.runs, "passed": 0, "failures": [], "transcripts": []}
        for _ in range(args.runs):
            run = run_case(case)
            failures = check(case, run)
            if "judge" in case.get("expect", {}):
                judge_failure, judge_input, judge_output = judge(case, run, judge_client)
                totals["judge_input"] += judge_input
                totals["judge_output"] += judge_output
                if judge_failure:
                    failures.append(judge_failure)
            totals["latch_input"] += run["input_tokens"]
            totals["latch_output"] += run["output_tokens"]
            totals["latch_cache_read"] += run["cache_read_tokens"]
            totals["latch_cache_write"] += run["cache_write_tokens"]
            totals["latency"] += run["latency_seconds"]
            result["passed"] += not failures
            result["failures"] += failures
            result["transcripts"].append({**run, "failures": failures})
        print(f"{'PASS' if result['passed'] == args.runs else 'FAIL'} {result['passed']}/{args.runs}  {case['id']}")
        results.append(result)

    report_path = write_report(results, args.runs, totals)
    passed = sum(result["passed"] for result in results)
    total = sum(result["runs"] for result in results)
    print(f"\n{passed}/{total} runs passed ({passed / total:.0%}) -- report: {report_path}")


if __name__ == "__main__":
    main()
