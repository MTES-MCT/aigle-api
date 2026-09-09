from django.test import SimpleTestCase

from core.utils.string import strip_email_subaddress


class StripEmailSubaddressTests(SimpleTestCase):
    def test_strips_the_tag(self):
        self.assertEqual(
            strip_email_subaddress("stephen+xyz@mail.com"), "stephen@mail.com"
        )

    def test_strips_from_the_first_plus_only(self):
        self.assertEqual(
            strip_email_subaddress("stephen+a+b@mail.com"), "stephen@mail.com"
        )

    def test_leaves_a_plain_address_untouched(self):
        self.assertEqual(strip_email_subaddress("stephen@mail.com"), "stephen@mail.com")

    def test_leaves_a_plus_in_the_domain_untouched(self):
        self.assertEqual(strip_email_subaddress("a@mail+x.com"), "a@mail+x.com")

    def test_keeps_the_original_when_the_local_part_would_be_empty(self):
        self.assertEqual(strip_email_subaddress("+xyz@mail.com"), "+xyz@mail.com")

    def test_keeps_a_string_without_an_arobase(self):
        self.assertEqual(strip_email_subaddress("pas-une-adresse"), "pas-une-adresse")

    def test_splits_on_the_last_arobase(self):
        self.assertEqual(strip_email_subaddress("a+b@c@mail.com"), "a@mail.com")
