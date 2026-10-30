import json
import unittest
from unittest.mock import Mock
from opencode_major_notice import reconcile, TITLE, MARKER
from update_opencode_release import fetch_release_pages, select_release
from test_update_opencode_release import release
from datetime import UTC, datetime

RUN = 'https://github.com/ubc/jupyter-images/actions/runs/123'


class ReleaseHistoryTests(unittest.TestCase):
    def test_supported_release_beyond_first_hundred_is_selected(self):
        first = [dict(release('2.2.0', '2026-10-27T00:00:00Z'), id=i) for i in range(100)]
        second = [dict(release('1.19.5', '2026-10-28T00:00:00Z'), id=101)]
        fetch = Mock(side_effect=[first, second])
        history = fetch_release_pages(fetch)
        chosen = select_release(history, '1.18.32', minimum_age_hours=48,
                                now=datetime(2026, 10, 30, 12, tzinfo=UTC))
        self.assertEqual(chosen['version'], '1.19.5')
        self.assertEqual([c.args for c in fetch.call_args_list], [(1,), (2,)])

    def test_incomplete_history_and_page_errors_cannot_be_quiet_success(self):
        page = [dict(id=i) for i in range(100)]
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            fetch_release_pages(lambda _: page, maximum_pages=1)
        with self.assertRaisesRegex(ValueError, 'pagination changed'):
            fetch_release_pages(lambda _: page)
        with self.assertRaisesRegex(ValueError, 'invalid release page'):
            fetch_release_pages(lambda _: {'error': 'rate limit'})
        with self.assertRaisesRegex(RuntimeError, 'network'):
            fetch_release_pages(Mock(side_effect=[page, RuntimeError('network')]))
        self.assertEqual(fetch_release_pages(lambda _: []), [])


class MajorNoticeTests(unittest.TestCase):
    def existing(self, version):
        return json.dumps([{'number': 11, 'title': TITLE, 'body': MARKER + version + ' -->\nReviewer notes'}])

    def test_create_update_noop_and_close(self):
        call = Mock(side_effect=['[]', 'created'])
        reconcile('2.2.0', RUN, call)
        self.assertEqual(call.call_args.args[:2], ('issue', 'create'))
        self.assertIn('2.2.0', call.call_args.kwargs['body'])
        call = Mock(return_value=self.existing('2.2.0'))
        reconcile('2.2.0', RUN, call)
        self.assertEqual(call.call_count, 1)
        call = Mock(side_effect=[self.existing('2.2.0'), 'updated'])
        reconcile('2.3.0', RUN, call)
        self.assertEqual(call.call_args.args[:3], ('issue', 'edit', '11'))
        call = Mock(side_effect=[self.existing('2.2.0'), 'closed'])
        reconcile('', RUN, call)
        self.assertEqual(call.call_args.args, ('issue', 'close', '11'))
        call = Mock(return_value='[]')
        reconcile('', RUN, call)
        self.assertEqual(call.call_count, 1)

    def test_unrelated_issue_and_untrusted_values_are_refused(self):
        call = Mock(return_value=json.dumps([{'number': 11, 'title': TITLE, 'body': 'Human issue'}]))
        with self.assertRaisesRegex(ValueError, 'unrelated'):
            reconcile('2.2.0', RUN, call)
        self.assertEqual(call.call_count, 1)
        for version, url in [('2.2.0\ninjected', RUN), ('2.2.0', 'https://example.test/')]:
            call = Mock()
            with self.assertRaises(ValueError):
                reconcile(version, url, call)
            call.assert_not_called()


if __name__ == '__main__':
    unittest.main()
