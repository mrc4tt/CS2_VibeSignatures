import unittest

from process_reporter import (
    EdgeType,
    ExecutionEdge,
    ExecutionJob,
    ExecutionNode,
    ExecutionPlan,
    ExecutionStage,
    PlanNodeType,
    ProcessPhase,
    ProcessReason,
    RunStatus,
    TaskStatus,
    build_job_id,
    build_stage_id,
    build_task_id,
    is_valid_run_transition,
    is_valid_task_transition,
)


class TestProcessReporterDomain(unittest.TestCase):
    def test_builds_stable_execution_identifiers(self) -> None:
        stage_id = build_stage_id(8, "engine")
        job_id = build_job_id(stage_id, "windows")

        self.assertEqual("stage-0008-engine", stage_id)
        self.assertEqual("stage-0008-engine-windows", job_id)
        self.assertEqual(
            "stage-0008-engine-windows/find-target",
            build_task_id(job_id, "find-target"),
        )

    def test_rejects_invalid_execution_identifier_parts(self) -> None:
        with self.assertRaises(ValueError):
            build_stage_id(-1, "engine")
        with self.assertRaises(ValueError):
            build_job_id("stage-0001-engine", "")
        with self.assertRaises(ValueError):
            build_task_id("stage-0001-engine-windows", "nested/task")

    def test_status_transitions_are_idempotent_and_terminal(self) -> None:
        self.assertTrue(is_valid_task_transition(TaskStatus.PENDING, TaskStatus.RUNNING))
        self.assertTrue(is_valid_task_transition(TaskStatus.RUNNING, TaskStatus.SUCCEEDED))
        self.assertTrue(is_valid_task_transition(TaskStatus.SUCCEEDED, TaskStatus.SUCCEEDED))
        self.assertFalse(is_valid_task_transition(TaskStatus.SUCCEEDED, TaskStatus.RUNNING))
        self.assertTrue(is_valid_run_transition(RunStatus.RUNNING, RunStatus.STALE))
        self.assertTrue(is_valid_run_transition(RunStatus.STALE, RunStatus.RUNNING))
        self.assertFalse(is_valid_run_transition(RunStatus.FAILED, RunStatus.RUNNING))

    def test_execution_plan_serializes_to_api_shape(self) -> None:
        stage = ExecutionStage(id="stage-0000-engine", stage_index=0, module_name="engine")
        job = ExecutionJob(
            id="stage-0000-engine-windows",
            stage_id=stage.id,
            stage_index=0,
            module_name="engine",
            platform="windows",
            binary_path="bin/14141/engine/engine2.dll",
        )
        node = ExecutionNode(
            id=f"{job.id}/find-target",
            job_id=job.id,
            stage_id=stage.id,
            name="find-target",
            node_type=PlanNodeType.SKILL,
            order=0,
            layer=0,
            data={"status": TaskStatus.PENDING, "phase": ProcessPhase.PREFLIGHT},
        )
        plan = ExecutionPlan(
            stages=[stage],
            jobs=[job],
            nodes=[node],
            edges=[
                ExecutionEdge(
                    source=stage.id,
                    target=job.id,
                    edge_type=EdgeType.STAGE_ORDER,
                )
            ],
            warnings=[ProcessReason.GRAPH_INVALID],
        )

        payload = plan.to_dict()

        self.assertEqual(1, payload["schema_version"])
        self.assertEqual("skill", payload["nodes"][0]["node_type"])
        self.assertEqual("pending", payload["nodes"][0]["data"]["status"])
        self.assertEqual("preflight", payload["nodes"][0]["data"]["phase"])
        self.assertEqual("stage_order", payload["edges"][0]["edge_type"])
        self.assertEqual(["graph_invalid"], payload["warnings"])


if __name__ == "__main__":
    unittest.main()
