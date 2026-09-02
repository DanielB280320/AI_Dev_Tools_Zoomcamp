from django import forms

from .models import FeedbackEntry, Project, User


class IdentifyForm(forms.Form):
    """Name entry on load (spec §8). Matches an existing user or creates one."""

    name = forms.CharField(
        max_length=80,
        label="Your name",
        widget=forms.TextInput(attrs={"autofocus": True, "placeholder": "e.g. Daniel"}),
    )

    def clean_name(self):
        return self.cleaned_data["name"].strip()

    def get_or_create_user(self):
        name = self.cleaned_data["name"]
        # Names are the identity, so match case-insensitively to avoid
        # "daniel" and "Daniel" becoming two people.
        user = User.objects.filter(name__iexact=name).first()
        if user is None:
            user = User.objects.create(name=name)
        return user


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["name"]
        widgets = {"name": forms.TextInput(attrs={"autofocus": True})}


class FeedbackEntryForm(forms.ModelForm):
    """Status + note, and nothing else -- submission under 30 seconds (§8)."""

    class Meta:
        model = FeedbackEntry
        fields = ["status", "note"]
        widgets = {
            "status": forms.RadioSelect,
            "note": forms.Textarea(
                attrs={"rows": 3, "placeholder": "What's going on? (optional)"}
            ),
        }
        labels = {"note": "Note"}


class AddMemberForm(forms.Form):
    """Managers add members by name (spec §2.3)."""

    name = forms.CharField(max_length=80, label="Add member by name")

    def clean_name(self):
        return self.cleaned_data["name"].strip()

    def get_or_create_user(self):
        name = self.cleaned_data["name"]
        user = User.objects.filter(name__iexact=name).first()
        if user is None:
            user = User.objects.create(name=name)
        return user
