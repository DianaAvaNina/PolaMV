from pathlib import Path
import pytest
from polamv.deployment import driver_command, DRIVER_FILES


def test_driver_install_command_is_fixed_and_preserves_unicode_spaces(tmp_path, monkeypatch):
    root = tmp_path/'中文 folder'
    folder = root/'vendor/Drivers/Usb3.0'
    folder.mkdir(parents=True)
    for name in DRIVER_FILES: (folder/name).write_bytes(b'test')
    monkeypatch.setenv('WINDIR', 'C:/Windows')
    command = driver_command(root)
    assert command[1:] == ['/add-driver', str((folder/'mvu3v.inf').resolve()), '/install']
    assert Path(command[0]).name == 'pnputil.exe'
    assert not any(flag in command for flag in ('/reboot', '/delete-driver', '/force'))


def test_missing_driver_files_fail_before_install(tmp_path):
    with pytest.raises(FileNotFoundError): driver_command(tmp_path)
