import shutil
import tempfile
from pathlib import Path

import pytest
from reflex_base import constants
from click.testing import CliRunner
from reflex_base.config import Config
from reflex_base.constants.installer import PackageJson
from reflex_base.utils.decorator import cached_procedure

from reflex.reflex import cli
from reflex.testing import chdir
from reflex.utils import build, frontend_skeleton
from reflex.utils.frontend_skeleton import (
    _compile_package_json,
    _update_sveltekit_layout_config,
    _compile_vite_config,
    _update_react_router_config,
)
from reflex.utils.prerequisites import needs_reinit
from reflex.utils.rename import rename_imports_and_app_name
from reflex.utils.telemetry import CpuInfo, get_cpu_info

runner = CliRunner()


@pytest.mark.parametrize(
    ("config", "export", "expected_output"),
    [
        (
            Config(
                app_name="test",
            ),
            False,
            'export default {"basename": "/", "future": {"unstable_optimizeDeps": true}, "ssr": false};',
        ),
        (
            Config(
                app_name="test",
                static_page_generation_timeout=30,
            ),
            False,
            'export default {"basename": "/", "future": {"unstable_optimizeDeps": true}, "ssr": false};',
        ),
        (
            Config(
                app_name="test",
                frontend_path="/test",
            ),
            False,
            'export default {"basename": "/test/", "future": {"unstable_optimizeDeps": true}, "ssr": false};',
        ),
        (
            Config(
                app_name="test",
            ),
            True,
            'export default {"basename": "/", "future": {"unstable_optimizeDeps": true}, "ssr": false, "prerender": true, "build": "build"};',
        ),
    ],
)
def test_update_react_router_config(config, export, expected_output):
    output = _update_react_router_config(config, prerender_routes=export)
    assert output == expected_output


@pytest.mark.parametrize(
    ("config", "expected_output"),
    [
        (
            Config(
                app_name="test",
                frontend_path="",
            ),
            'assetsDir: "/assets".slice(1),',
        ),
        (
            Config(
                app_name="test",
                frontend_path="/test",
            ),
            'assetsDir: "/test/assets".slice(1),',
        ),
        (
            Config(
                app_name="test",
                frontend_path="/test/",
            ),
            'assetsDir: "/test/assets".slice(1),',
        ),
    ],
)
def test_initialise_vite_config(config, expected_output):
    output = _compile_vite_config(config)
    assert expected_output in output


@pytest.mark.parametrize(
    ("frontend_path", "expected_command"),
    [
        ("", "sirv ./build/client --single 404.html --host"),
        ("/", "sirv ./build/client --single 404.html --host"),
        ("/app", "sirv ./build/client --single app/404.html --host"),
        ("/app/", "sirv ./build/client --single app/404.html --host"),
        ("app", "sirv ./build/client --single app/404.html --host"),
        (
            "/deep/nested/path",
            "sirv ./build/client --single deep/nested/path/404.html --host",
        ),
    ],
)
def test_get_prod_command(frontend_path, expected_command):
    assert PackageJson.Commands.get_prod_command(frontend_path) == expected_command


@pytest.mark.parametrize(
    ("config", "expected_prod_script"),
    [
        (
            Config(app_name="test"),
            "sirv ./build/client --single 404.html --host",
        ),
        (
            Config(app_name="test", frontend_path="/app"),
            "sirv ./build/client --single app/404.html --host",
        ),
        (
            Config(app_name="test", frontend_path="/deep/nested"),
            "sirv ./build/client --single deep/nested/404.html --host",
        ),
    ],
)
def test_compile_package_json_prod_command(config, expected_prod_script, monkeypatch):
    monkeypatch.setattr("reflex.utils.frontend_skeleton.get_config", lambda: config)
    output = _compile_package_json()
    assert f'"prod": "{expected_prod_script}"' in output


@pytest.mark.parametrize(
    ("frontend_path", "expected_command"),
    [
        ("", "sirv ./build/client --single 200.html --host"),
        ("/", "sirv ./build/client --single 200.html --host"),
        ("/app", "sirv ./build/client --single app/200.html --host"),
    ],
)
def test_get_sveltekit_prod_command(frontend_path, expected_command):
    assert (
        PackageJson.Commands.get_sveltekit_prod_command(frontend_path)
        == expected_command
    )


def test_compile_package_json_sveltekit(monkeypatch):
    config = Config(
        app_name="test",
        frontend_target=constants.FrontendTarget.SVELTEKIT,
    )
    monkeypatch.setattr("reflex.utils.frontend_skeleton.get_config", lambda: config)
    output = _compile_package_json()
    assert '"dev": "vite dev --host"' in output
    assert '"export": "vite build"' in output
    assert '"prod": "sirv ./build/client --single 200.html --host"' in output
    assert '"@radix-ui/themes"' in output
    assert '"@sveltejs/kit"' in output
    assert '"@tailwindcss/postcss"' in output
    assert '"lucide-svelte"' in output
    assert '"react-router"' not in output


def test_needs_reinit_when_web_template_mismatches_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """A stale React .web skeleton should be rebuilt for a Svelte target."""

    reflex_dir = tmp_path / ".reflex"
    reflex_dir.mkdir()
    web_dir = tmp_path / ".web"
    web_dir.mkdir()
    (web_dir / "react-router.config.js").write_text("export default {};")

    monkeypatch.setenv("REFLEX_DIR", str(reflex_dir))
    monkeypatch.setenv("REFLEX_WEB_WORKDIR", str(web_dir))
    monkeypatch.setattr(
        "reflex.utils.prerequisites.get_config",
        lambda: Config(
            app_name="test",
            frontend_target=constants.FrontendTarget.SVELTEKIT,
        ),
    )
    monkeypatch.setattr(
        "reflex.utils.prerequisites._is_app_compiled_with_same_reflex_version",
        lambda: True,
    )

    assert needs_reinit() is True


def test_needs_reinit_when_sveltekit_generated_modules_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """A stale SvelteKit skeleton missing generated modules should be rebuilt."""

    reflex_dir = tmp_path / ".reflex"
    reflex_dir.mkdir()
    web_dir = tmp_path / ".web"
    (web_dir / "src" / "routes").mkdir(parents=True)
    (web_dir / "svelte.config.js").write_text("export default {};")
    (web_dir / "src" / "routes" / "+layout.svelte").write_text("<slot />")

    monkeypatch.setenv("REFLEX_DIR", str(reflex_dir))
    monkeypatch.setenv("REFLEX_WEB_WORKDIR", str(web_dir))
    monkeypatch.setattr(
        "reflex.utils.prerequisites.get_config",
        lambda: Config(
            app_name="test",
            frontend_target=constants.FrontendTarget.SVELTEKIT,
        ),
    )
    monkeypatch.setattr(
        "reflex.utils.prerequisites._is_app_compiled_with_same_reflex_version",
        lambda: True,
    )

    assert needs_reinit() is True


def test_svelte_generated_modules_are_written(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """SvelteKit metadata modules should be written into src/lib/reflex/generated."""

    web_dir = tmp_path / ".web"
    monkeypatch.setenv("REFLEX_WEB_WORKDIR", str(web_dir))

    config = Config(
        app_name="test",
        api_url="http://localhost:8000",
        frontend_target=constants.FrontendTarget.SVELTEKIT,
    )
    monkeypatch.setattr("reflex.utils.frontend_skeleton.get_config", lambda: config)
    monkeypatch.setattr("reflex.utils.build.get_config", lambda: config)
    monkeypatch.setattr("reflex_base.config.get_config", lambda: config)

    frontend_skeleton.init_reflex_json(project_hash=123)
    build.set_env_json()

    reflex_module = web_dir / "src" / "lib" / "reflex" / "generated" / "reflex.js"
    env_module = web_dir / "src" / "lib" / "reflex" / "generated" / "env.js"

    assert reflex_module.exists()
    assert env_module.exists()
    assert (
        reflex_module.read_text()
        == f'export default {{"project_hash": 123, "version": "{constants.Reflex.VERSION}"}};\n'
    )
    env_text = env_module.read_text()
    assert env_text.startswith("export default ")
    assert '"PING": "http://localhost:8000/ping"' in env_text
    assert '"EVENT": "ws://localhost:8000/_event"' in env_text


def test_sveltekit_layout_keeps_ssr_enabled_for_prerender():
    """SvelteKit prerendering needs SSR enabled during the build."""

    layout_config = (
        constants.Templates.Dirs.WEB_SVELTEKIT_TEMPLATE
        / "src"
        / "routes"
        / "+layout.js"
    ).read_text()

    assert "export const prerender = !dev;" in layout_config
    assert "export const ssr = dev;" not in layout_config


@pytest.mark.parametrize(
    ("prerender_routes", "expected_output"),
    [
        (False, "export const prerender = false;\n"),
        (True, "export const prerender = true;\n"),
    ],
)
def test_update_sveltekit_layout_config(prerender_routes, expected_output):
    output = _update_sveltekit_layout_config(
        Config(
            app_name="test",
            frontend_target=constants.FrontendTarget.SVELTEKIT,
        ),
        prerender_routes=prerender_routes,
    )
    assert output == expected_output


def test_cached_procedure():
    call_count = 0

    temp_file = tempfile.mktemp()

    @cached_procedure(
        cache_file_path=lambda: Path(temp_file), payload_fn=lambda: "constant"
    )
    def _function_with_no_args():
        nonlocal call_count
        call_count += 1

    _function_with_no_args()
    assert call_count == 1
    _function_with_no_args()
    assert call_count == 1

    call_count = 0

    another_temp_file = tempfile.mktemp()

    @cached_procedure(
        cache_file_path=lambda: Path(another_temp_file),
        payload_fn=lambda *args, **kwargs: f"{repr(args), repr(kwargs)}",
    )
    def _function_with_some_args(*args, **kwargs):
        nonlocal call_count
        call_count += 1

    _function_with_some_args(1, y=2)
    assert call_count == 1
    _function_with_some_args(1, y=2)
    assert call_count == 1
    _function_with_some_args(100, y=300)
    assert call_count == 2
    _function_with_some_args(100, y=300)
    assert call_count == 2

    call_count = 0

    @cached_procedure(
        cache_file_path=lambda: Path(tempfile.mktemp()), payload_fn=lambda: "constant"
    )
    def _function_with_no_args_fn():
        nonlocal call_count
        call_count += 1

    _function_with_no_args_fn()
    assert call_count == 1
    _function_with_no_args_fn()
    assert call_count == 2


def test_get_cpu_info():
    cpu_info = get_cpu_info()
    assert cpu_info is not None
    assert isinstance(cpu_info, CpuInfo)
    assert cpu_info.model_name is not None

    for attr in ("manufacturer_id", "model_name", "address_width"):
        value = getattr(cpu_info, attr)
        assert value.strip() if attr != "address_width" else value


@pytest.fixture
def temp_directory():
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    shutil.rmtree(temp_dir)


@pytest.mark.parametrize(
    ("config_code", "expected"),
    [
        ("rx.Config(app_name='old_name')", 'rx.Config(app_name="new_name")'),
        ('rx.Config(app_name="old_name")', 'rx.Config(app_name="new_name")'),
        ("rx.Config('old_name')", 'rx.Config("new_name")'),
        ('rx.Config("old_name")', 'rx.Config("new_name")'),
    ],
)
def test_rename_imports_and_app_name(temp_directory, config_code, expected):
    file_path = temp_directory / "rxconfig.py"
    content = f"""
config = {config_code}
"""
    file_path.write_text(content)

    rename_imports_and_app_name(file_path, "old_name", "new_name")

    updated_content = file_path.read_text()
    expected_content = f"""
config = {expected}
"""
    assert updated_content == expected_content


def test_regex_edge_cases(temp_directory):
    file_path = temp_directory / "example.py"
    content = """
from old_name.module import something
import old_name
from old_name import something_else as alias
from old_name
"""
    file_path.write_text(content)

    rename_imports_and_app_name(file_path, "old_name", "new_name")

    updated_content = file_path.read_text()
    expected_content = """
from new_name.module import something
import new_name
from new_name import something_else as alias
from new_name
"""
    assert updated_content == expected_content


def test_cli_rename_command(temp_directory):
    foo_dir = temp_directory / "foo"
    foo_dir.mkdir()
    (foo_dir / "__init__").touch()
    (foo_dir / ".web").mkdir()
    (foo_dir / "assets").mkdir()
    (foo_dir / "foo").mkdir()
    (foo_dir / "foo" / "__init__.py").touch()
    (foo_dir / "rxconfig.py").touch()
    (foo_dir / "rxconfig.py").write_text(
        """
import reflex as rx

config = rx.Config(
    app_name="foo",
)
"""
    )
    (foo_dir / "foo" / "components").mkdir()
    (foo_dir / "foo" / "components" / "__init__.py").touch()
    (foo_dir / "foo" / "components" / "base.py").touch()
    (foo_dir / "foo" / "components" / "views.py").touch()
    (foo_dir / "foo" / "components" / "base.py").write_text(
        """
import reflex as rx
from foo.components import views
from foo.components.views import *
from .base import *

def random_component():
    return rx.fragment()
"""
    )
    (foo_dir / "foo" / "foo.py").touch()
    (foo_dir / "foo" / "foo.py").write_text(
        """
import reflex as rx
import foo.components.base
from foo.components.base import random_component

class State(rx.State):
  pass


def index():
   return rx.text("Hello, World!")

app = rx.App()
app.add_page(index)
"""
    )

    with chdir(temp_directory / "foo"):
        result = runner.invoke(cli, ["rename", "bar"])

    assert result.exit_code == 0, result.output
    assert (foo_dir / "rxconfig.py").read_text() == (
        """
import reflex as rx

config = rx.Config(
    app_name="bar",
)
"""
    )
    assert (foo_dir / "bar").exists()
    assert not (foo_dir / "foo").exists()
    assert (foo_dir / "bar" / "components" / "base.py").read_text() == (
        """
import reflex as rx
from bar.components import views
from bar.components.views import *
from .base import *

def random_component():
    return rx.fragment()
"""
    )
    assert (foo_dir / "bar" / "bar.py").exists()
    assert not (foo_dir / "bar" / "foo.py").exists()
    assert (foo_dir / "bar" / "bar.py").read_text() == (
        """
import reflex as rx
import bar.components.base
from bar.components.base import random_component

class State(rx.State):
  pass


def index():
   return rx.text("Hello, World!")

app = rx.App()
app.add_page(index)
"""
    )
