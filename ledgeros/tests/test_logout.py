from django.contrib.auth import SESSION_KEY, get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from ledgeros.roles import ROLE_ADMIN, assign_user_role


class LogoutTests(TestCase):
    def test_navigation_logout_ends_session_with_csrf_protection(self):
        user = get_user_model().objects.create_user(username="logout-test")
        assign_user_role(user, ROLE_ADMIN)
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)

        response = client.get(reverse("property-list"))
        self.assertContains(response, 'method="post" action="/logout/"')
        self.assertNotContains(response, '<a href="/logout/">')
        token = client.cookies["csrftoken"].value

        self.assertEqual(client.post(reverse("logout")).status_code, 403)
        self.assertIn(SESSION_KEY, client.session)
        response = client.post(reverse("logout"), {"csrfmiddlewaretoken": token})
        self.assertRedirects(response, reverse("login"))
        self.assertNotIn(SESSION_KEY, client.session)
