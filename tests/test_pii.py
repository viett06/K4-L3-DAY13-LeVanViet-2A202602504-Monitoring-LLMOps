from app.pii import scrub_text


def test_scrub_email() -> None:
    out = scrub_text("Email me at student@vinuni.edu.vn")
    assert "student@" not in out
    assert "REDACTED_EMAIL" in out


def test_scrub_common_vietnamese_phone_formats() -> None:
    phone_numbers = (
        "0901234567",
        "090 123 4567",
        "090.123.4567",
        "090-123-4567",
        "+84 90 123 4567",
    )

    for phone_number in phone_numbers:
        out = scrub_text(f"Contact: {phone_number}")
        assert phone_number not in out
        assert "REDACTED_PHONE_VN" in out


def test_scrub_cccd_and_payment_card() -> None:
    out = scrub_text("CCCD 079203001234, card 4111-1111-1111-1111 and 4111 1111 1111 1111")
    assert "079203001234" not in out
    assert "4111" not in out
    assert "REDACTED_CCCD" in out
    assert "REDACTED_CREDIT_CARD" in out


def test_scrub_passport_and_vietnamese_address() -> None:
    out = scrub_text(
        "Ho chieu B1234567. So nha 12 duong Le Loi, phuong Ben Nghe, quan 1, thanh pho Ho Chi Minh. "
        "Số nhà 25 đường Lê Lợi, phường Bến Nghé, quận 1, thành phố Hồ Chí Minh."
    )
    assert "B1234567" not in out
    assert "Le Loi" not in out
    assert "Lê Lợi" not in out
    assert "Ben Nghe" not in out
    assert "Bến Nghé" not in out
    assert "Ho Chi Minh" not in out
    assert "Hồ Chí Minh" not in out
    assert "REDACTED_PASSPORT" in out
    assert "REDACTED_VN_ADDRESS" in out
