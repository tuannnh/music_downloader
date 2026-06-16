"""Generate an Apple Shortcuts (.shortcut) file for the Share Sheet.

The produced shortcut takes the shared URL (from YouTube/TikTok), POSTs it to
this app's /api/download endpoint with the Bearer token, and shows a
notification. It's an *unsigned* shortcut, so importing it on iOS requires
Settings -> Shortcuts -> "Allow Untrusted Shortcuts" to be enabled once.
"""

from __future__ import annotations

import plistlib
import uuid

# Menu shown when the shortcut runs: (label the user taps, format sent to API).
FORMAT_CHOICES: list[tuple[str, str]] = [
    ("M4A (best, lossless for YouTube/TikTok)", "m4a"),
    ("Opus (lossless if source is Opus)", "opus"),
    ("MP3 320", "mp3"),
]


def _text(string: str) -> dict:
    """A plain-text token (no embedded variables)."""
    return {
        "WFSerializationType": "WFTextTokenString",
        "Value": {"string": string, "attachmentsByRange": {}},
    }


def _shortcut_input_token() -> dict:
    """A text field whose entire content is the Shortcut Input variable."""
    return {
        "WFSerializationType": "WFTextTokenString",
        "Value": {
            # U+FFFC OBJECT REPLACEMENT CHARACTER marks the attachment slot.
            "string": "￼",
            "attachmentsByRange": {"{0, 1}": {"Type": "ExtensionInput"}},
        },
    }


def _dict_field(items: list[tuple[dict, dict]]) -> dict:
    """Build a WFDictionaryFieldValue from (key_token, value_token) pairs."""
    return {
        "WFSerializationType": "WFDictionaryFieldValue",
        "Value": {
            "WFDictionaryFieldValueItems": [
                {"WFItemType": 0, "WFKey": key, "WFValue": value}
                for key, value in items
            ]
        },
    }


def _download_action(api_url: str, token: str, fmt: str) -> dict:
    """A 'Get Contents of URL' POST with the URL (shared input) + chosen format."""
    return {
        "WFWorkflowActionIdentifier": "is.workflow.actions.downloadurl",
        "WFWorkflowActionParameters": {
            "WFURL": api_url,
            "WFHTTPMethod": "POST",
            "ShowHeaders": True,
            "WFHTTPHeaders": _dict_field(
                [(_text("Authorization"), _text(f"Bearer {token}"))]
            ),
            "WFHTTPBodyType": "JSON",
            "WFJSONValues": _dict_field(
                [
                    (_text("url"), _shortcut_input_token()),
                    (_text("format"), _text(fmt)),
                ]
            ),
        },
    }


def build_shortcut(api_url: str, token: str, notify_title: str = "Copytele") -> bytes:
    """Return the binary plist bytes for the shortcut file.

    When run, it asks the user to pick an audio format (a "Choose from Menu"),
    then POSTs the shared URL + chosen format to the API.
    """
    group = str(uuid.uuid4()).upper()

    # Menu start: lists the choices.
    actions = [
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.choosefrommenu",
            "WFWorkflowActionParameters": {
                "GroupingIdentifier": group,
                "WFControlFlowMode": 0,
                "WFMenuPrompt": "Download audio as…",
                "WFMenuItems": [label for label, _ in FORMAT_CHOICES],
            },
        }
    ]
    # One branch per choice: case header + the matching download action.
    for label, fmt in FORMAT_CHOICES:
        actions.append(
            {
                "WFWorkflowActionIdentifier": "is.workflow.actions.choosefrommenu",
                "WFWorkflowActionParameters": {
                    "GroupingIdentifier": group,
                    "WFControlFlowMode": 1,
                    "WFMenuItemTitle": label,
                },
            }
        )
        actions.append(_download_action(api_url, token, fmt))
    # Menu end.
    actions.append(
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.choosefrommenu",
            "WFWorkflowActionParameters": {
                "GroupingIdentifier": group,
                "WFControlFlowMode": 2,
            },
        }
    )
    # Confirmation notification (runs after whichever branch was taken).
    actions.append(
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.shownotification",
            "WFWorkflowActionParameters": {
                "WFNotificationActionTitle": notify_title,
                "WFNotificationActionBody": "✅ Sent to Copytele",
            },
        }
    )

    workflow = {
        "WFWorkflowActions": actions,
        "WFWorkflowClientVersion": "1146.0.2.2",
        "WFWorkflowMinimumClientVersion": 411,
        "WFWorkflowMinimumClientVersionString": "411",
        "WFWorkflowHasShortcutInputVariables": True,
        "WFWorkflowIcon": {
            "WFWorkflowIconStartColor": 946986751,
            "WFWorkflowIconGlyphNumber": 61440,
        },
        "WFWorkflowImportQuestions": [],
        "WFWorkflowInputContentItemClasses": [
            "WFArticleContentItem",
            "WFContactContentItem",
            "WFDateContentItem",
            "WFEmailAddressContentItem",
            "WFGenericFileContentItem",
            "WFImageContentItem",
            "WFiTunesProductContentItem",
            "WFLocationContentItem",
            "WFDCMapsLinkContentItem",
            "WFAVAssetContentItem",
            "WFPDFContentItem",
            "WFPhoneNumberContentItem",
            "WFRichTextContentItem",
            "WFSafariWebPageContentItem",
            "WFStringContentItem",
            "WFURLContentItem",
        ],
        "WFWorkflowTypes": ["ActionExtension"],
    }

    return plistlib.dumps(workflow, fmt=plistlib.FMT_BINARY)
