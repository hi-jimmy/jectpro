from django.core.files.uploadedfile import SimpleUploadedFile

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from transactions.management.commands.sync_open_data import make_record
from transactions.management.commands.sync_seoul_archives import ArchiveListParser, normalize_csv_row
from .models import SeoulOpenRecord


class DashboardTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="reporter", email="reporter@example.com", password="test-password-123")

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_root_redirects_to_living_population_page(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(response, "/data/living/", fetch_redirect_response=False)

    def test_legacy_transaction_chart_redirects_to_login(self):
        response = self.client.get(reverse("chart_data"))
        self.assertEqual(response.status_code, 302)

    def test_signup_and_reset_pages_are_public(self):
        self.assertEqual(self.client.get("/accounts/signup/").status_code, 200)
        self.assertEqual(self.client.get("/accounts/password-reset/").status_code, 200)

    def test_password_reset_sends_one_time_link_to_email(self):
        response = self.client.post("/accounts/password-reset/", {"email": "reporter@example.com"})
        self.assertRedirects(response, "/accounts/password-reset/done/")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/accounts/reset/", mail.outbox[0].body)

    def test_signup_creates_user_and_logs_them_in(self):
        response = self.client.post("/accounts/signup/", {
            "username": "new-reporter",
            "email": "new-reporter@example.com",
            "password1": "Strong-local-pass-947!",
            "password2": "Strong-local-pass-947!",
        })
        self.assertRedirects(response, "/data/living/")
        self.assertTrue(get_user_model().objects.filter(username="new-reporter").exists())
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    def test_open_data_menu_shows_saved_api_records(self):
        self.client.force_login(self.user)
        SeoulOpenRecord.objects.create(dataset="living", record_key="grid-test", period="20261020", cell_id="test-grid", metric_value=12, metric_label="생활인구")
        response = self.client.get("/data/living/?q=test-grid")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["records"][0].cell_id, "test-grid")
        self.assertContains(response, "test-grid")
        self.assertContains(response, "원본 필드")
        self.assertNotContains(response, "record.trade_name|default")

    def test_open_data_chart_requires_login(self):
        response = self.client.get("/api/open-data-chart/living/")
        self.assertEqual(response.status_code, 302)
        self.client.force_login(self.user)
        response = self.client.get("/api/open-data-chart/living/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("timeline", response.json())

    def test_login_page_has_login_signup_and_reset_actions(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, "로그인")
        self.assertContains(response, "아이디 생성")
        self.assertContains(response, "비밀번호 찾기")

    def test_official_archive_list_parser_extracts_download_sequence(self):
        parser = ArchiveListParser()
        parser.feed('<table><tr id="fileTr_1"><td>1</td><td>데이터</td><td><span title="sample.zip" onclick="downloadFile(\'51\')">sample.zip</span></td><td>13.7</td><td>2026.05.18</td></tr></table>')
        self.assertEqual(parser.files[0]["name"], "sample.zip")
        self.assertEqual(parser.files[0]["seq"], "51")
        self.assertEqual(parser.files[0]["size_mb"], 13.7)

    def test_official_population_csv_maps_to_indexed_dataset_fields(self):
        row = normalize_csv_row({"일자": "20261020", "시간": "00", "행정동코드": "11110515", "250M격자": "다사52255325", "생활인구합계": "4.26", "남자 0~9세": "*"})
        record = make_record("living", row)
        self.assertEqual(record.period, "20261020")
        self.assertEqual(record.cell_id, "다사52255325")
        self.assertEqual(str(record.metric_value), "4.26")
        self.assertEqual(record.payload["남자 0~9세"], "*")
        other_hour = make_record("living", {**row, "시간": "01"})
        self.assertNotEqual(record.record_key, other_hour.record_key)

    def test_annual_store_and_sales_csv_fields_are_mapped(self):
        store = make_record("store", {"STDR_YYQU_CD": "20251", "TRDAR_CD": "3001491", "TRDAR_CD_NM": "이태원", "SVC_INDUTY_CD": "CS300015", "SVC_INDUTY_CD_NM": "가방", "SIMILR_INDUTY_STOR_CO": "88"})
        sales = make_record("sales", {"기준_년분기_코드": "20251", "상권_코드": "3001491", "상권_코드_명": "이태원", "서비스_업종_코드": "CS300015", "서비스_업종_코드_명": "가방", "당월_매출_금액": "1569075360"})
        self.assertEqual(str(store.metric_value), "88")
        self.assertEqual(str(sales.metric_value), "1569075360")

    def test_admin_upload_page_is_staff_only(self):
        upload_url = reverse("admin:dataset_upload", kwargs={"dataset": "living"})
        response = self.client.get(upload_url)
        self.assertEqual(response.status_code, 302)
        staff_user = get_user_model().objects.create_superuser(username="upload-admin", email="upload@example.com", password="Strong-admin-pass-947!")
        self.client.force_login(staff_user)
        response = self.client.get(upload_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "파일을 여기로 끌어오세요")

    def test_admin_csv_upload_imports_rows(self):
        staff_user = get_user_model().objects.create_superuser(username="file-admin", email="file@example.com", password="Strong-admin-pass-948!")
        self.client.force_login(staff_user)
        content = "일자,시간,행정동코드,250M격자,생활인구합계\n20261020,00,11110515,다사52255325,4.26\n".encode("utf-8-sig")
        uploaded = SimpleUploadedFile("population.csv", content, content_type="text/csv")
        upload_url = reverse("admin:dataset_upload", kwargs={"dataset": "living"})
        response = self.client.post(upload_url, {"file": uploaded, "replace_existing": "on"})
        self.assertRedirects(response, upload_url, fetch_redirect_response=False)
        self.assertTrue(SeoulOpenRecord.objects.filter(dataset="living", cell_id="다사52255325").exists())