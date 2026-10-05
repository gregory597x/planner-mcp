"""Offline tests: the validation that stands between the model and the hub, and
the deterministic tree. No hub, no Ollama.  Run: python3 -m unittest -v"""

import unittest

from planner_agent import AgentError, render_tree, request_task_ids, validate_action

BLANK = {"task_id": None, "depends_on_id": None, "title": None, "description": None,
         "category": None, "status": None, "priority": None, "due_date": None,
         "role": None, "work_with": [], "unblocks": [], "depends_on": [], "note": None}


def args(**kw):
    a = dict(BLANK)
    a.update(kw)
    return a


class TaskIds(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(request_task_ids("#86 depends on task 73 and task #5"), {86, 73, 5})

    def test_plain_numbers_are_not_ids(self):
        self.assertEqual(request_task_ids("gap is 250 mm, 0.5 T"), set())


class Validate(unittest.TestCase):
    def test_invented_task_id_is_rejected(self):
        # The case seen live: deepseek returned task_id 12345 for a create request.
        with self.assertRaises(AgentError):
            validate_action("add_dependency", args(task_id=12345, depends_on_id=1), "decide the pole ratio")

    def test_create_keeps_only_what_the_request_supports(self):
        req = "Add a task for Greg to decide the pole-face ratio, work with role-solver-b, MRI, priority 2"
        plan, warn = validate_action("create_task", args(
            title="Decide the pole-face ratio", category="MRI", priority=2, due_date="2026-10-01",
            role="role-owner", work_with=["role-solver-b", "code-role-viewer-c-01"], depends_on=[41]), req)
        self.assertEqual(plan["method"], "POST")
        self.assertEqual(plan["body"], {"title": "Decide the pole-face ratio", "category": "MRI",
                                        "priority": 2, "role": "role-owner", "work_with": ["role-solver-b"]})
        joined = " ".join(warn)
        for dropped in ("due_date", "code-role-viewer-c-01", "depends_on 41"):
            self.assertIn(dropped, joined)

    def test_for_me_means_personal(self):
        plan, _ = validate_action("create_task", args(title="Call the FDA lawyer"), "remind me: task for me to call the FDA lawyer")
        self.assertEqual(plan["body"]["role"], "role-owner")

    def test_phrase_copied_as_role_becomes_personal(self):
        # Seen live: the model returned role "for me".
        plan, _ = validate_action("create_task", args(title="Decide the ratio", role="for me"),
                                  "Add a task for me to decide the ratio")
        self.assertEqual(plan["body"]["role"], "role-owner")

    def test_role_not_in_request_is_dropped(self):
        plan, warn = validate_action("create_task", args(title="x", role="role-solver-b"), "add a task x")
        self.assertNotIn("role", plan["body"])
        self.assertTrue(any("role" in w for w in warn))

    def test_date_must_be_written_out(self):
        plan, _ = validate_action("create_task", args(title="x", due_date="2026-10-08"), "add task x due 2026-10-08")
        self.assertEqual(plan["body"]["due_date"], "2026-10-08")

    def test_update_cannot_complete(self):
        with self.assertRaises(AgentError):  # status dropped -> nothing left to change
            validate_action("update_task", args(task_id=73, status="Completed"), "set #73 Completed")

    def test_close_uses_status_endpoint_with_note(self):
        plan, _ = validate_action("close_task", args(task_id=41, note="spec landed"), "#41 is done, spec landed")
        self.assertEqual((plan["method"], plan["path"]), ("POST", "/role-planner/tasks/41/status"))
        self.assertEqual(plan["body"], {"status": "Completed", "note": "spec landed"})

    def test_dependency_needs_both_ids_from_request(self):
        plan, _ = validate_action("add_dependency", args(task_id=86, depends_on_id=73), "#86 depends on #73")
        self.assertEqual(plan["path"], "/role-planner/tasks/86/dependencies")
        self.assertEqual(plan["body"], {"depends_on": [73]})
        with self.assertRaises(AgentError):
            validate_action("add_dependency", args(task_id=86, depends_on_id=99), "#86 depends on #73")

    def test_self_dependency_rejected(self):
        with self.assertRaises(AgentError):
            validate_action("add_dependency", args(task_id=86, depends_on_id=86), "#86 depends on #86")

    def test_remove_dependency(self):
        plan, _ = validate_action("remove_dependency", args(task_id=86, depends_on_id=73), "#86 no longer waits on #73")
        self.assertEqual((plan["method"], plan["path"], plan["body"]), ("DELETE", "/role-planner/tasks/86/dependencies/73", None))


class Tree(unittest.TestCase):
    TASKS = [
        {"task_id": 73, "title": "Finish LOADER_MIGRATION", "status": "Pending", "priority": 3,
         "due_date": "2026-07-27", "category": "SOFTWARE", "role": None, "work_with": [],
         "unblocks": [], "dependencies": [], "dependents": [86], "is_blocked": False},
        {"task_id": 86, "title": "Call-site migration", "status": "Pending", "priority": 3,
         "due_date": "2026-07-27", "category": "SOFTWARE", "role": None, "work_with": ["viewer-stack-01"],
         "unblocks": [], "dependencies": [73], "dependents": [], "is_blocked": True},
        {"task_id": 200, "title": "Decide pole ratio", "status": "Pending", "priority": 1,
         "due_date": None, "category": "MRI", "role": "role-owner", "work_with": ["role-solver-b"],
         "unblocks": ["pitch field claim"], "dependencies": [], "dependents": [], "is_blocked": False},
    ]

    def test_shape(self):
        out = render_tree(self.TASKS)
        self.assertEqual(out.splitlines()[0], "MRI  (1)")
        self.assertIn("└── role-owner", out)
        self.assertIn("[⛔] #86 Call-site migration", out)
        self.assertIn("waits on: #73", out)
        self.assertIn("blocks:   #86", out)
        self.assertIn("unblocks: pitch field claim", out)
        self.assertIn("(no role)", out)

    def test_empty(self):
        self.assertEqual(render_tree([]), "(no tasks)")


if __name__ == "__main__":
    unittest.main()
