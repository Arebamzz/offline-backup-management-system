import os
import posixpath
import shutil


def exists(target):
    return os.path.exists(target)


def ensure_dir(target, mode):
    os.makedirs(target, mode=mode, exist_ok=True)


def has_any_file(root):
    if not os.path.isdir(root):
        return False

    for _, _, files in os.walk(root):
        if files:
            return True

    return False


def count_files_and_bytes(root):
    files = 0
    bytes_total = 0

    for directory, _, file_names in os.walk(root):
        for file_name in file_names:
            file_path = os.path.join(directory, file_name)
            if os.path.isfile(file_path):
                files += 1
                bytes_total += os.path.getsize(file_path)

    return {"files": files, "bytes": bytes_total}


def list_child_directories(root):
    return sorted(
        posixpath.join(root, entry)
        for entry in os.listdir(root)
        if os.path.isdir(posixpath.join(root, entry))
    )


def list_relative_files(root):
    files = []

    for directory, _, file_names in os.walk(root):
        for file_name in file_names:
            file_path = os.path.join(directory, file_name)
            if os.path.isfile(file_path):
                files.append(os.path.relpath(file_path, root).replace(os.sep, "/"))

    return sorted(files)


def chmod_tree(root, dir_mode, file_mode):
    for directory, subdirectories, file_names in os.walk(root):
        os.chmod(directory, dir_mode)

        for subdirectory in subdirectories:
            os.chmod(os.path.join(directory, subdirectory), dir_mode)

        for file_name in file_names:
            file_path = os.path.join(directory, file_name)
            if os.path.isfile(file_path):
                os.chmod(file_path, file_mode)


def remove_path(target):
    if os.path.isdir(target) and not os.path.islink(target):
        shutil.rmtree(target)
    else:
        try:
            os.remove(target)
        except FileNotFoundError:
            pass


def parse_mode(value):
    if isinstance(value, int):
        return value
    return int(str(value), 8)


def format_bytes(bytes_total):
    units = ["B", "K", "M", "G", "T", "P"]
    value = float(bytes_total)
    unit_index = 0

    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024
        unit_index += 1

    if unit_index == 0:
        return "{}B".format(int(value))

    if value >= 10:
        return "{:.0f}{}".format(value, units[unit_index])

    return "{:.1f}{}".format(value, units[unit_index])
