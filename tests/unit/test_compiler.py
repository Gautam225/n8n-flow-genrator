"""Unit tests for the Workflow Compiler service."""
import pytest
from backend.app.schemas.ir import (
    ConnectionType,
    IREdge,
    IRNode,
    NodeExecutionPolicy,
    NodePosition,
    WorkflowIR,
    WorkflowSettings,
)
from backend.app.services.compiler import CompilationError, WorkflowCompiler, compile_workflow


def test_linear_workflow_compilation():
    """Verifies compilation of a standard 3-node linear pipeline."""
    workflow = WorkflowIR(
        id="wf_linear_001",
        name="Linear Sync Pipeline",
        nodes=[
            IRNode(id="node_1", name="Schedule Trigger", node_type="n8n-nodes-base.scheduleTrigger", type_version=1.2),
            IRNode(id="node_2", name="Fetch API Data", node_type="n8n-nodes-base.httpRequest", type_version=4.2),
            IRNode(id="node_3", name="Store Postgres", node_type="n8n-nodes-base.postgres", type_version=2.5),
        ],
        edges=[
            IREdge(source_id="node_1", target_id="node_2", connection_type=ConnectionType.MAIN),
            IREdge(source_id="node_2", target_id="node_3", connection_type=ConnectionType.MAIN),
        ],
    )

    compiled = compile_workflow(workflow)

    assert compiled["name"] == "Linear Sync Pipeline"
    assert compiled["active"] is False
    assert len(compiled["nodes"]) == 3

    # Check connection array structure
    conn = compiled["connections"]
    assert "Schedule Trigger" in conn
    assert conn["Schedule Trigger"]["main"][0] == [{"node": "Fetch API Data", "type": "main", "index": 0}]
    assert conn["Fetch API Data"]["main"][0] == [{"node": "Store Postgres", "type": "main", "index": 0}]
    assert "Store Postgres" not in conn  # Leaf node has no outgoing connections


def test_if_branching_compilation():
    """Verifies that If node branches (output 0=True, 1=False) compile to distinct sub-arrays."""
    workflow = WorkflowIR(
        id="wf_if_001",
        name="Conditional Routing",
        nodes=[
            IRNode(id="n_trig", name="Webhook", node_type="n8n-nodes-base.webhook", type_version=2.0),
            IRNode(id="n_if", name="Evaluate Condition", node_type="n8n-nodes-base.if", type_version=2.3),
            IRNode(id="n_true", name="True Handler", node_type="n8n-nodes-base.noOp", type_version=1.0),
            IRNode(id="n_false", name="False Handler", node_type="n8n-nodes-base.noOp", type_version=1.0),
        ],
        edges=[
            IREdge(source_id="n_trig", target_id="n_if", source_output_index=0),
            IREdge(source_id="n_if", target_id="n_true", source_output_index=0),   # True branch
            IREdge(source_id="n_if", target_id="n_false", source_output_index=1),  # False branch
        ],
    )

    compiled = compile_workflow(workflow)
    if_conns = compiled["connections"]["Evaluate Condition"]["main"]

    assert len(if_conns) == 2
    assert if_conns[0] == [{"node": "True Handler", "type": "main", "index": 0}]
    assert if_conns[1] == [{"node": "False Handler", "type": "main", "index": 0}]


def test_parallel_fan_out_and_fan_in_compilation():
    """Verifies fan-out (multiple targets on one socket) and fan-in (Merge node receiving on indices 0 and 1)."""
    workflow = WorkflowIR(
        id="wf_parallel_001",
        name="Parallel Fan-Out Fan-In",
        nodes=[
            IRNode(id="n_start", name="Start", node_type="n8n-nodes-base.manualTrigger"),
            IRNode(id="n_task_a", name="Fetch Orders", node_type="n8n-nodes-base.httpRequest"),
            IRNode(id="n_task_b", name="Fetch Users", node_type="n8n-nodes-base.httpRequest"),
            IRNode(id="n_merge", name="Merge Datasets", node_type="n8n-nodes-base.merge", type_version=3.0),
        ],
        edges=[
            # Fan-out from Start
            IREdge(source_id="n_start", target_id="n_task_a", source_output_index=0),
            IREdge(source_id="n_start", target_id="n_task_b", source_output_index=0),
            # Fan-in to Merge
            IREdge(source_id="n_task_a", target_id="n_merge", source_output_index=0, target_input_index=0),
            IREdge(source_id="n_task_b", target_id="n_merge", source_output_index=0, target_input_index=1),
        ],
    )

    compiled = compile_workflow(workflow)

    # Fan-out check: Start output 0 contains both targets
    start_main = compiled["connections"]["Start"]["main"][0]
    assert len(start_main) == 2
    targets = {target["node"] for target in start_main}
    assert targets == {"Fetch Orders", "Fetch Users"}

    # Fan-in check
    assert compiled["connections"]["Fetch Orders"]["main"][0] == [
        {"node": "Merge Datasets", "type": "main", "index": 0}
    ]
    assert compiled["connections"]["Fetch Users"]["main"][0] == [
        {"node": "Merge Datasets", "type": "main", "index": 1}
    ]


def test_error_connection_compilation():
    """Verifies that error flow edges compile to 'error' connection keys."""
    workflow = WorkflowIR(
        id="wf_err_001",
        name="Error Handling Workflow",
        nodes=[
            IRNode(id="n_trig", name="Trigger", node_type="n8n-nodes-base.manualTrigger"),
            IRNode(id="n_risky", name="Risky API Call", node_type="n8n-nodes-base.httpRequest"),
            IRNode(id="n_err_handler", name="Log Failure", node_type="n8n-nodes-base.noOp"),
        ],
        edges=[
            IREdge(source_id="n_trig", target_id="n_risky", connection_type=ConnectionType.MAIN),
            IREdge(source_id="n_risky", target_id="n_err_handler", connection_type=ConnectionType.ERROR),
        ],
    )

    compiled = compile_workflow(workflow)
    risky_conns = compiled["connections"]["Risky API Call"]

    assert "error" in risky_conns
    assert risky_conns["error"][0] == [
        {"node": "Log Failure", "type": "error", "index": 0}
    ]


def test_valid_loop_structure_compilation():
    """Verifies compilation of a controlled loop (SplitInBatches with cycle)."""
    workflow = WorkflowIR(
        id="wf_loop_001",
        name="Batch Processing Loop",
        nodes=[
            IRNode(id="n_start", name="Start", node_type="n8n-nodes-base.manualTrigger"),
            IRNode(id="n_loop", name="Loop Over Items", node_type="n8n-nodes-base.splitInBatches", type_version=3.0),
            IRNode(id="n_proc", name="Process Batch Item", node_type="n8n-nodes-base.httpRequest"),
            IRNode(id="n_done", name="Notify Completed", node_type="n8n-nodes-base.noOp"),
        ],
        edges=[
            IREdge(source_id="n_start", target_id="n_loop", source_output_index=0),
            # Loop body: output 0 -> process item -> loop back
            IREdge(source_id="n_loop", target_id="n_proc", source_output_index=0),
            IREdge(source_id="n_proc", target_id="n_loop", source_output_index=0, target_input_index=0),
            # Loop completion: output 1 -> notify
            IREdge(source_id="n_loop", target_id="n_done", source_output_index=1),
        ],
    )

    compiled = compile_workflow(workflow)
    loop_main = compiled["connections"]["Loop Over Items"]["main"]

    assert len(loop_main) == 2
    assert loop_main[0] == [{"node": "Process Batch Item", "type": "main", "index": 0}]
    assert loop_main[1] == [{"node": "Notify Completed", "type": "main", "index": 0}]

    # Loop back edge from Process Batch Item
    proc_main = compiled["connections"]["Process Batch Item"]["main"]
    assert proc_main[0] == [{"node": "Loop Over Items", "type": "main", "index": 0}]


def test_deterministic_compilation_output():
    """Verifies that compiling identical input repeatedly produces strictly identical JSON."""
    workflow = WorkflowIR(
        id="wf_determ_001",
        name="Deterministic Test",
        nodes=[
            IRNode(id="n_b", name="Second Node", node_type="n8n-nodes-base.noOp"),
            IRNode(id="n_a", name="First Node", node_type="n8n-nodes-base.manualTrigger"),
        ],
        edges=[
            IREdge(source_id="n_a", target_id="n_b"),
        ],
    )

    compiler = WorkflowCompiler()
    json_1 = compiler.compile_to_json(workflow)
    json_2 = compiler.compile_to_json(workflow)

    assert json_1 == json_2


def test_execution_policy_preservation():
    """Verifies that node execution policies (retryOnFail, continueOnFail) are preserved."""
    workflow = WorkflowIR(
        id="wf_policy_001",
        name="Policy Test",
        nodes=[
            IRNode(
                id="n_1",
                name="Flaky HTTP",
                node_type="n8n-nodes-base.httpRequest",
                execution_policy=NodeExecutionPolicy(
                    continue_on_fail=True,
                    retry_on_fail=True,
                    max_tries=5,
                    wait_between_tries=2000,
                ),
            )
        ],
    )

    compiled = compile_workflow(workflow)
    node_data = compiled["nodes"][0]

    assert node_data["continueOnFail"] is True
    assert node_data["retryOnFail"] is True
    assert node_data["maxTries"] == 5
    assert node_data["waitBetweenTries"] == 2000


def test_workflow_settings_compilation():
    """Verifies compilation of workflow-level runtime settings."""
    workflow = WorkflowIR(
        id="wf_settings_001",
        name="Settings Test",
        nodes=[IRNode(id="n1", name="Start", node_type="n8n-nodes-base.manualTrigger")],
        settings=WorkflowSettings(
            execution_timeout=120,
            timezone="UTC",
            save_manual_executions=False,
            error_workflow_id="wf_global_err_handler",
        ),
    )

    compiled = compile_workflow(workflow)
    settings = compiled["settings"]

    assert settings["executionTimeout"] == 120
    assert settings["timezone"] == "UTC"
    assert settings["saveManualExecutions"] is False
    assert settings["errorWorkflow"] == "wf_global_err_handler"


def test_duplicate_node_name_raises_compilation_error():
    """Verifies that identical node display names raise CompilationError."""
    # We bypass Pydantic model validator for IDs by giving distinct IDs but identical names
    workflow = WorkflowIR(
        id="wf_dup_name_001",
        name="Duplicate Name Workflow",
        nodes=[
            IRNode(id="n_1", name="Duplicate Label", node_type="n8n-nodes-base.manualTrigger"),
            IRNode(id="n_2", name="Duplicate Label", node_type="n8n-nodes-base.noOp"),
        ],
    )

    with pytest.raises(CompilationError, match="Duplicate node display name"):
        compile_workflow(workflow)


def test_explicit_canvas_coordinates_preservation():
    """Verifies that non-zero coordinates in IR are preserved by the compiler."""
    workflow = WorkflowIR(
        id="wf_coords_001",
        name="Coordinates Workflow",
        nodes=[
            IRNode(
                id="n1",
                name="Start",
                node_type="n8n-nodes-base.manualTrigger",
                position=NodePosition(x=123.0, y=456.0),
            ),
        ],
    )

    compiled = compile_workflow(workflow)
    assert compiled["nodes"][0]["position"] == [123.0, 456.0]


def test_native_n8n_structure_validation_integration():
    """Validates compiled workflow against n8n's real safeParseWorkflowStructure if Docker is active."""
    import json
    import shutil
    import subprocess

    if not shutil.which("docker"):
        pytest.skip("Docker CLI not available")

    workflow = WorkflowIR(
        id="wf_native_check",
        name="Native Validation Pipeline",
        nodes=[
            IRNode(id="n_trig", name="Schedule", node_type="n8n-nodes-base.scheduleTrigger"),
            IRNode(id="n_http", name="API Call", node_type="n8n-nodes-base.httpRequest", parameters={"url": "https://api.example.com"}),
        ],
        edges=[IREdge(source_id="n_trig", target_id="n_http")],
    )

    compiled = compile_workflow(workflow)

    js_check = f"""
    try {{
        const {{ safeParseWorkflowStructure }} = require('/usr/local/lib/node_modules/n8n/node_modules/n8n-workflow');
        const res = safeParseWorkflowStructure({json.dumps(compiled)});
        console.log(JSON.stringify(res));
    }} catch (err) {{
        console.log(JSON.stringify({{ success: false, error: err.message }}));
    }}
    """

    try:
        res = subprocess.run(
            ["docker", "exec", "-i", "n8n-local", "node", "-e", js_check],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if res.returncode != 0:
            pytest.skip("Docker container n8n-local not running or unreachable")
    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        pytest.skip("Docker container n8n-local unreachable or command timed out")

    parsed = json.loads(res.stdout)
    assert parsed.get("success") is True, f"Native n8n schema validation failed: {parsed}"

