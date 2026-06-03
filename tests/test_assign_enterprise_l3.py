import csv
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "assign_enterprise_l3.py"
SPEC = importlib.util.spec_from_file_location("assign_enterprise_l3", SCRIPT_PATH)
assign_enterprise_l3 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = assign_enterprise_l3
SPEC.loader.exec_module(assign_enterprise_l3)


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["工单ID", "工单链接", "受理人", "状态", "优先级", "标题"],
        )
        writer.writeheader()
        writer.writerows(rows)


class AssignEnterpriseL3Test(unittest.TestCase):
    def test_load_target_tickets_skips_solved_and_closed_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            csv_path = Path(tmp_dir) / "tickets.csv"
            write_csv(
                csv_path,
                [
                    {"工单ID": "1753", "受理人": "workflow_rag@dify.ai", "状态": "open"},
                    {"工单ID": "896", "受理人": "workflow_rag@dify.ai", "状态": "solved"},
                    {"工单ID": "999", "受理人": "workflow_rag@dify.ai", "状态": "closed"},
                ],
            )

            tickets = assign_enterprise_l3.load_target_tickets(
                csv_path, include_solved=False
            )

        self.assertEqual([ticket.ticket_id for ticket in tickets], [1753])

    def test_build_assignment_payload_sets_enterprise_l3_assignee(self) -> None:
        payload = assign_enterprise_l3.build_assignment_payload(
            assignee_id=41232787009812,
            group_id=40685413533332,
        )

        self.assertEqual(
            payload,
            {
                "assignee_id": 41232787009812,
                "group_id": 40685413533332,
            },
        )
