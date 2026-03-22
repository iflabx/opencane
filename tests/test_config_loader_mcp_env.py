from __future__ import annotations

import json
from pathlib import Path

from opencane.config.loader import load_config, save_config


def test_load_config_preserves_mcp_env_var_key_casing(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "tools": {
                    "mcpServers": {
                        "demo": {
                            "command": "npx",
                            "args": ["-y"],
                            "env": {
                                "OPENAI_API_KEY": "k1",
                                "X-Custom-Token": "token",
                                "MY_VAR_2": "v2",
                            },
                        }
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    cfg = load_config(config_path)
    env = cfg.tools.mcp_servers["demo"].env

    assert env["OPENAI_API_KEY"] == "k1"
    assert env["X-Custom-Token"] == "token"
    assert env["MY_VAR_2"] == "v2"
    assert "o_p_e_n_a_i__a_p_i__k_e_y" not in env


def test_save_config_preserves_mcp_env_var_key_casing(tmp_path: Path) -> None:
    in_path = tmp_path / "in.json"
    out_path = tmp_path / "out.json"
    in_path.write_text(
        json.dumps(
            {
                "tools": {
                    "mcpServers": {
                        "demo": {
                            "command": "npx",
                            "env": {
                                "OPENAI_API_KEY": "k1",
                                "X-Custom-Token": "token",
                            },
                        }
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    cfg = load_config(in_path)
    save_config(cfg, out_path)
    dumped = json.loads(out_path.read_text(encoding="utf-8"))
    env = dumped["tools"]["mcpServers"]["demo"]["env"]

    assert env["OPENAI_API_KEY"] == "k1"
    assert env["X-Custom-Token"] == "token"
    assert "oPENAIAPIKEY" not in env
