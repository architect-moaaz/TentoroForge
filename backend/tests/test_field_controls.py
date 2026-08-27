"""`resolve_control` is the single deterministic authority for a form field's control
type. These lock the priority order (FK > enum > semantic > SQL type > name > default)
and the exact node/prop shapes both the deterministic builder and the post-gen pass
depend on."""
from services.field_controls import resolve_control


def test_plain_varchar_names_are_input():
    for n in ("firstName", "name", "email"):
        control, props = resolve_control(name=n, sql_type="varchar")
        assert control == "Input", n
        assert props == {}, n


def test_email_semantic_hint_sets_input_type():
    control, props = resolve_control(name="email", sql_type="varchar", semantic_type="email")
    assert control == "Input"
    assert props == {"type": "email"}


def test_fk_target_is_select_with_optionsfrom_target_slug():
    control, props = resolve_control(name="roomId", sql_type="uuid", fk_target="Room")
    assert control == "Select"
    assert props["optionsFrom"]["source"] == "rooms"
    assert props["optionsFrom"]["value"] == "id"
    assert props["optionsFrom"]["label"] == "name"


def test_fk_derived_from_name_when_no_target():
    control, props = resolve_control(name="candidateId", sql_type="uuid")
    assert control == "Select"
    assert props["optionsFrom"]["source"] == "candidates"


def test_bare_id_is_not_treated_as_fk():
    control, _ = resolve_control(name="id", sql_type="uuid")
    assert control != "Select"


def test_enum_options_become_select():
    control, props = resolve_control(name="status", sql_type="varchar",
                                     options=["Active", "Closed"])
    assert control == "Select"
    assert props["options"] == [
        {"value": "Active", "label": "Active"},
        {"value": "Closed", "label": "Closed"},
    ]


def test_currency_semantic_on_numeric_is_moneyish_numberinput():
    control, props = resolve_control(name="amount", sql_type="numeric",
                                     semantic_type="currency")
    assert control == "NumberInput"
    assert props["prefix"] == "$"
    assert props["showSteppers"] is False
    assert props["step"] == 0.01
    assert props["min"] == 0


def test_sql_type_boolean_is_switch():
    control, props = resolve_control(name="isActive", sql_type="boolean")
    assert control == "Switch"
    assert props == {}


def test_sql_type_timestamp_is_datepicker():
    control, props = resolve_control(name="createdAt", sql_type="timestamp")
    assert control == "DatePicker"
    assert props == {}


def test_sql_type_integer_is_numberinput_step_one():
    control, props = resolve_control(name="quantity", sql_type="integer")
    assert control == "NumberInput"
    assert props == {"min": 0, "step": 1}


def test_sql_type_text_is_textarea():
    control, props = resolve_control(name="body", sql_type="text")
    assert control == "Textarea"
    assert props == {}


def test_name_description_varchar_is_textarea():
    control, props = resolve_control(name="description", sql_type="varchar")
    assert control == "Textarea"


def test_incompatible_currency_hint_on_varchar_is_ignored():
    # `currency` is a numeric-flavoured hint; on a varchar column it is a mistake and
    # is dropped, falling through to the plain Input default.
    control, props = resolve_control(name="referenceCode", sql_type="varchar",
                                     semantic_type="currency")
    assert control == "Input"
    assert props == {}


def test_document_url_columns_are_fileupload():
    # A CV/resume/document/attachment/photo/avatar column is stored as a text/varchar
    # URL but must render a FileUpload, never a Textarea — caught before the
    # text→Textarea return and before the varchar name-heuristic block.
    for n in ("cvUrl", "resumeUrl", "documentUrl", "attachmentUrl",
              "avatarUrl", "photoUrl"):
        control, props = resolve_control(name=n, sql_type="text")
        assert control == "FileUpload", n
        assert isinstance(props, dict), n
        # Only props FileUpload's schema accepts may be emitted.
        assert set(props).issubset(
            {"accept", "multiple", "maxSizeMb", "hint"}), (n, props)


def test_bare_document_noun_is_fileupload():
    for n in ("cv", "resume", "document", "attachment", "photo", "avatar",
              "headshot", "logo", "upload", "scan"):
        control, _ = resolve_control(name=n, sql_type="varchar")
        assert control == "FileUpload", n


def test_file_semantic_hint_is_fileupload():
    for hint in ("file", "upload", "document", "attachment"):
        control, _ = resolve_control(name="cvUrl", sql_type="text", semantic_type=hint)
        assert control == "FileUpload", hint


def test_long_text_columns_stay_textarea_not_fileupload():
    # Negatives: long-text columns must NOT be mistaken for file uploads.
    for n in ("description", "notes", "summary", "comments", "bio",
              "content", "message", "address"):
        control, _ = resolve_control(name=n, sql_type="text")
        assert control == "Textarea", n


def test_non_file_url_column_is_not_fileupload():
    # A *Url column whose stem is NOT a document noun is not a file upload.
    for n in ("profileUrl", "websiteUrl", "callbackUrl"):
        control, _ = resolve_control(name=n, sql_type="text")
        assert control != "FileUpload", n


def test_deterministic_same_inputs_same_output():
    kwargs = dict(name="salaryAmount", sql_type="numeric", not_null=True,
                  semantic_type="currency")
    a = resolve_control(**kwargs)
    b = resolve_control(**kwargs)
    assert a == b
    assert a == ("NumberInput", {"min": 0, "step": 0.01, "prefix": "$", "showSteppers": False})
