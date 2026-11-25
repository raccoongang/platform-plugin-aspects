#!/usr/bin/env python
"""
Test basic SupersetXBlock display function
"""

from unittest import TestCase
from unittest.mock import Mock, patch

from opaque_keys.edx.locator import CourseLocator
from webob import Request
from xblock.field_data import DictFieldData
from xblock.reference.user_service import XBlockUser

from ..xblock import SupersetXBlock


def make_an_xblock(user_role, **kwargs):
    """
    Helper method that creates a new SupersetXBlock
    """
    course_id = CourseLocator("foo", "bar", "baz")
    mock_user = Mock(
        spec=XBlockUser,
        opt_attrs={
            "edx-platform.username": user_role,
            "edx-platform.user_role": user_role,
        },
    )

    def service(block, service):  # pylint: disable=unused-argument
        # Mock the user service
        if service == "user":
            return Mock(get_current_user=Mock(return_value=mock_user))
        # Mock the i18n service
        return Mock(_catalog={})

    def local_resource_url(_self, url):
        return url

    def handler_url(_self, handler, *args, **kwargs):
        """
        Mock runtime.handlerUrl

        The LMS and CMS runtimes implement handlerUrl, but we have to mock it here.
        """
        return f"/{handler}"

    runtime = Mock(
        course_id=course_id,
        service=service,
        local_resource_url=Mock(side_effect=local_resource_url),
        handlerUrl=Mock(side_effect=handler_url),
    )

    scope_ids = Mock()
    field_data = DictFieldData(kwargs)
    xblock = SupersetXBlock(runtime, field_data, scope_ids)
    xblock.xmodule_runtime = runtime
    return xblock


class TestRender(TestCase):
    """
    Test the HTML rendering of the XBlock
    """

    def test_render_instructor(self):
        """
        Ensure staff can see the Superset dashboard.
        """
        xblock = make_an_xblock("instructor")
        student_view = xblock.student_view()
        html = student_view.content
        self.assertIsNotNone(html)
        self.assertIn(
            "Dashboard UUID is not set. Please set the dashboard UUID in the Studio.",
            html,
        )

    def test_render_student(self):
        """
        Ensure students see a warning message, not Superset.
        """
        xblock = make_an_xblock("student")
        student_view = xblock.student_view()
        html = student_view.content
        self.assertIsNotNone(html)
        self.assertNotIn("superset-embedded-container", html)
        self.assertIn("Superset is only visible to course staff and instructors", html)

    @patch("platform_plugin_aspects.xblock.translation.get_language")
    def test_render_translations(self, mock_get_language):
        """
        Ensure translated javascript is served.
        """
        mock_get_language.return_value = "eo"
        xblock = make_an_xblock("instructor")
        student_view = xblock.student_view()
        url_resource = None
        for resource in student_view.resources:
            if resource.kind == "url":
                url_resource = resource
                self.assertIsNotNone(
                    url_resource, "No 'url' resource found in fragment"
                )
                self.assertIn("eo/text.js", url_resource.data)
        mock_get_language.assert_called_once()

    @patch("platform_plugin_aspects.xblock.translation.get_language")
    def test_render_no_translations(
        self,
        mock_get_language,
    ):
        """
        Ensure translated javascript is served.
        """
        mock_get_language.return_value = None
        xblock = make_an_xblock("instructor")
        student_view = xblock.student_view()
        for resource in student_view.resources:
            assert resource.kind != "url"
        mock_get_language.assert_called_once()


class TestGuestTokenPermissions(TestCase):
    """
    Harrow: the XBlock handler gives nobody a guest token, course staff included.
    """

    def setUp(self):
        """
        Mock guest token generation; it must never run for denied users.
        """
        super().setUp()
        patcher = patch("platform_plugin_aspects.xblock.generate_guest_token")
        self.addCleanup(patcher.stop)
        self.mock_generate_guest_token = patcher.start()

    def _call_handler(self, xblock):
        """
        POST to the guest token handler and return the response.
        """
        request = Request.blank("/")
        request.method = "POST"
        request.body = b"{}"
        return xblock.get_superset_guest_token(request)

    def _assert_denied(self, xblock):
        """
        Assert the handler refused the request without generating a token.
        """
        response = self._call_handler(xblock)

        assert response.status_code == 403
        self.mock_generate_guest_token.assert_not_called()

    def test_every_role_denied(self):
        # global staff are reported as "instructor" too
        for role in ("staff", "instructor", "student", "beta_tester"):
            with self.subTest(role=role):
                self._assert_denied(make_an_xblock(role))

    def test_no_role_denied(self):
        # e.g. an anonymous user, whose opt_attrs has no role
        xblock = make_an_xblock("student")
        user = xblock.runtime.service(xblock, "user").get_current_user()
        user.opt_attrs = {}
        self._assert_denied(xblock)

    def test_no_user_denied(self):
        xblock = make_an_xblock("instructor")
        xblock.runtime.service = Mock(
            return_value=Mock(get_current_user=Mock(return_value=None))
        )
        self._assert_denied(xblock)
