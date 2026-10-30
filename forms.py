from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm


class DatasetUploadForm(forms.Form):
    file = forms.FileField(label="CSV, XLSX 또는 공식 ZIP 파일")
    replace_existing = forms.BooleanField(label="같은 레코드 업데이트", required=False, initial=True)

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        extension = uploaded.name.rsplit(".", 1)[-1].lower() if "." in uploaded.name else ""
        if extension not in {"csv", "xlsx", "zip"}:
            raise forms.ValidationError("CSV, XLSX 또는 ZIP 파일만 업로드할 수 있습니다.")
        if uploaded.size > 100 * 1024 * 1024:
            raise forms.ValidationError("파일 크기는 100MB 이하여야 합니다.")
        return uploaded


class SignUpForm(UserCreationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].required = True

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username", "email")
