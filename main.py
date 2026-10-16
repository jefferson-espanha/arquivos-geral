from __future__ import annotations

import json
import os
import re
from html import escape
from typing import Any

import psycopg2
from psycopg2.extras import Json, RealDictCursor
from nicegui import ui

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("NEON_DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Configure DATABASE_URL nas variáveis de ambiente do Render.")

PORT = int(os.getenv("PORT", "8080"))
TABLE_NAME = "arquivos_gerais"
MAX_FILES = 80


def highlight_text(value: Any, term: str) -> str:
    """Escapa o texto e envolve cada ocorrência buscada em destaque vermelho."""
    text = escape(str(value or ""))
    escaped_term = escape(str(term or "").strip())
    if not escaped_term:
        return text
    return re.sub(
        re.escape(escaped_term),
        lambda match: f'<span class="search-highlight">{match.group(0)}</span>',
        text,
        flags=re.IGNORECASE,
    )


def get_connection():
    return psycopg2.connect(DATABASE_URL)


def initialize_database() -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                    id BIGSERIAL PRIMARY KEY,
                    local_arquivo TEXT NOT NULL DEFAULT '',
                    numero_caixa_pasta TEXT NOT NULL DEFAULT '',
                    numero_envelope TEXT NOT NULL DEFAULT '',
                    arquivos_contidos JSONB NOT NULL DEFAULT '[]'::jsonb,
                    link_arquivo TEXT NOT NULL DEFAULT '',
                    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        connection.commit()


def list_records(search: str = "") -> list[dict[str, Any]]:
    with get_connection() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            if search.strip():
                pattern = f"%{search.strip()}%"
                cursor.execute(
                    f"""
                    SELECT id, local_arquivo, numero_caixa_pasta, numero_envelope,
                           arquivos_contidos, link_arquivo
                    FROM {TABLE_NAME}
                    WHERE local_arquivo ILIKE %s
                       OR numero_caixa_pasta ILIKE %s
                       OR numero_envelope ILIKE %s
                       OR arquivos_contidos::text ILIKE %s
                       OR link_arquivo ILIKE %s
                    ORDER BY
                        CASE WHEN numero_caixa_pasta ~ '[0-9]+'
                             THEN substring(numero_caixa_pasta FROM '[0-9]+')::BIGINT
                             ELSE NULL END NULLS LAST,
                        numero_caixa_pasta ASC,
                        id ASC
                    """,
                    (pattern, pattern, pattern, pattern, pattern),
                )
            else:
                cursor.execute(
                    f"""
                    SELECT id, local_arquivo, numero_caixa_pasta, numero_envelope,
                           arquivos_contidos, link_arquivo
                    FROM {TABLE_NAME}
                    ORDER BY
                        CASE WHEN numero_caixa_pasta ~ '[0-9]+'
                             THEN substring(numero_caixa_pasta FROM '[0-9]+')::BIGINT
                             ELSE NULL END NULLS LAST,
                        numero_caixa_pasta ASC,
                        id ASC
                    """
                )

            rows = []
            for row in cursor.fetchall():
                item = dict(row)
                arquivos = item.get("arquivos_contidos") or []
                if isinstance(arquivos, str):
                    arquivos = json.loads(arquivos)
                normalized = []
                for arquivo in arquivos:
                    if isinstance(arquivo, dict):
                        normalized.append({
                            "numero_envelope": str(arquivo.get("numero_envelope", item.get("numero_envelope", "") or "")).strip(),
                            "nome": str(arquivo.get("nome", "")).strip(),
                            "assunto": str(arquivo.get("assunto", "")).strip(),
                            "interessado": str(arquivo.get("interessado", "")).strip(),
                            "link": str(arquivo.get("link", "")).strip(),
                        })
                    else:
                        normalized.append({
                            "numero_envelope": str(item.get("numero_envelope", "") or "").strip(),
                            "nome": str(arquivo).strip(),
                            "assunto": "",
                            "interessado": "",
                            "link": str(item.get("link_arquivo", "") or "").strip(),
                        })
                item["arquivos_contidos"] = normalized
                item["local_html"] = highlight_text(item.get("local_arquivo"), search)
                item["caixa_html"] = highlight_text(item.get("numero_caixa_pasta"), search)
                for arquivo in normalized:
                    arquivo["numero_envelope_html"] = highlight_text(arquivo.get("numero_envelope"), search)
                    arquivo["nome_html"] = highlight_text(arquivo.get("nome"), search)
                    arquivo["assunto_html"] = highlight_text(arquivo.get("assunto"), search)
                    arquivo["interessado_html"] = highlight_text(arquivo.get("interessado"), search)
                    arquivo["link_html"] = highlight_text(arquivo.get("link"), search)
                rows.append(item)
            return rows


def save_record(data: dict[str, Any], record_id: int | None = None) -> None:
    arquivos = [
        {
            "numero_envelope": str(value.get("numero_envelope", "")).strip(),
            "nome": str(value.get("nome", "")).strip(),
            "assunto": str(value.get("assunto", "")).strip(),
            "interessado": str(value.get("interessado", "")).strip(),
            "link": str(value.get("link", "")).strip(),
        }
        for value in data["arquivos_contidos"]
        if any(str(value.get(chave, "")).strip() for chave in ("numero_envelope", "nome", "assunto", "interessado", "link"))
    ]
    if len(arquivos) > MAX_FILES:
        raise ValueError(f"É permitido cadastrar no máximo {MAX_FILES} arquivos.")

    with get_connection() as connection:
        with connection.cursor() as cursor:
            values = (
                data["local_arquivo"],
                data["numero_caixa_pasta"],
                "",
                Json(arquivos),
                "",
            )
            if record_id is None:
                cursor.execute(
                    f"""
                    INSERT INTO {TABLE_NAME}
                        (local_arquivo, numero_caixa_pasta, numero_envelope, arquivos_contidos, link_arquivo)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    values,
                )
            else:
                cursor.execute(
                    f"""
                    UPDATE {TABLE_NAME}
                    SET local_arquivo = %s,
                        numero_caixa_pasta = %s,
                        numero_envelope = %s,
                        arquivos_contidos = %s,
                        link_arquivo = %s
                    WHERE id = %s
                    """,
                    values + (record_id,),
                )
        connection.commit()


def delete_record(record_id: int) -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(f"DELETE FROM {TABLE_NAME} WHERE id = %s", (record_id,))
        connection.commit()


initialize_database()

COLUMNS = [
    {"name": "local_arquivo", "label": "Caixa de arquivo", "field": "local_arquivo", "align": "left", "sortable": True},
    {"name": "numero_caixa_pasta", "label": "Nº da caixa/pasta", "field": "numero_caixa_pasta", "align": "left"},
    {"name": "arquivos_contidos", "label": "Arquivos e links", "field": "arquivos_contidos", "align": "left"},
]


@ui.page("/")
def main_page() -> None:
    search_input: ui.input
    record_table: ui.table
    dialog: ui.dialog
    total_label: ui.label
    results_panel: ui.html
    fields: dict[str, Any] = {}
    file_inputs: list[Any] = []
    files_container: Any = None
    current_id: int | None = None

    def build_search_results(rows: list[dict[str, Any]], term: str) -> str:
        if not term.strip():
            return ""
        cards = []
        for row in rows:
            files = []
            for arquivo in row.get("arquivos_contidos", []):
                files.append(
                    f'''<div class="search-file">
                        <b>Arquivo:</b> {arquivo.get("nome_html", "")}
                        <span><b>Envelope:</b> {arquivo.get("numero_envelope_html", "") or "Não informado"}</span>
                        <span><b>Assunto:</b> {arquivo.get("assunto_html", "") or "Não informado"}</span>
                        <span><b>Interessado:</b> {arquivo.get("interessado_html", "") or "Não informado"}</span>
                        <span><b>Link:</b> {arquivo.get("link_html", "") or "Não informado"}</span>
                    </div>'''
                )
            cards.append(
                f'''<div class="search-result-card">
                    <div class="search-result-title">Resultado encontrado</div>
                    <div><b>Caixa de arquivo:</b> {row.get("local_html", "")}</div>
                    <div><b>Número da caixa/pasta:</b> {row.get("caixa_html", "")}</div>
                    {"".join(files)}
                </div>'''
            )
        return f'<div class="search-results-title">Resultados para: <span class="search-highlight">{escape(term.strip())}</span></div>{"".join(cards)}'

    def refresh_table() -> None:
        term = search_input.value or ""
        record_table.rows = list_records(term)
        record_table.update()
        total_label.set_text(f"{len(record_table.rows)} registro(s) exibido(s)")
        results_panel.content = build_search_results(record_table.rows, term)
        results_panel.update()

    def close_dialog() -> None:
        dialog.close()

    def rebuild_file_inputs(values: list[dict[str, str]] | None = None) -> None:
        nonlocal file_inputs
        values = (values or [])[:MAX_FILES]
        file_inputs = []
        files_container.clear()
        with files_container:
            for index, value in enumerate(values, start=1):
                with ui.column().classes("w-full gap-1 border rounded-lg p-2 bg-gray-50"):
                    ui.label(f"Arquivo {index}").classes("text-subtitle2 font-semibold text-gray-700")
                    with ui.row().classes("w-full items-center gap-2"):
                        envelope_input = ui.input("Número do envelope", value=value.get("numero_envelope", "")).props("outlined dense").classes("w-48")
                        name_input = ui.input("Nome do arquivo", value=value.get("nome", "")).props("outlined dense").classes("flex-1")
                        subject_input = ui.input("Assunto do arquivo", value=value.get("assunto", "")).props("outlined dense").classes("flex-1")
                    with ui.row().classes("w-full items-center gap-2"):
                        interested_input = ui.input("Interessado", value=value.get("interessado", "")).props("outlined dense").classes("flex-1")
                        link_input = ui.input("Link do arquivo", value=value.get("link", "")).props("outlined dense").classes("flex-1")
                    file_inputs.append({
                        "numero_envelope": envelope_input,
                        "nome": name_input,
                        "assunto": subject_input,
                        "interessado": interested_input,
                        "link": link_input,
                    })

    def add_file_field() -> None:
        if len(file_inputs) >= MAX_FILES:
            ui.notify(f"Limite de {MAX_FILES} arquivos atingido.", type="warning")
            return
        values = [
            {
                "numero_envelope": str(pair["numero_envelope"].value or ""),
                "nome": str(pair["nome"].value or ""),
                "assunto": str(pair["assunto"].value or ""),
                "interessado": str(pair["interessado"].value or ""),
                "link": str(pair["link"].value or ""),
            }
            for pair in file_inputs
        ]
        values.append({"numero_envelope": "", "nome": "", "assunto": "", "interessado": "", "link": ""})
        rebuild_file_inputs(values)

    def collect_form() -> dict[str, Any]:
        return {
            "local_arquivo": str(fields["local_arquivo"].value or "").strip(),
            "numero_caixa_pasta": str(fields["numero_caixa_pasta"].value or "").strip(),
            "arquivos_contidos": [
                {
                    "numero_envelope": str(pair["numero_envelope"].value or "").strip(),
                    "nome": str(pair["nome"].value or "").strip(),
                    "assunto": str(pair["assunto"].value or "").strip(),
                    "interessado": str(pair["interessado"].value or "").strip(),
                    "link": str(pair["link"].value or "").strip(),
                }
                for pair in file_inputs
            ],
        }

    def save_form() -> None:
        data = collect_form()
        if not data["local_arquivo"]:
            ui.notify("Selecione o local de arquivo.", type="warning")
            return
        if not data["numero_caixa_pasta"]:
            ui.notify("Informe o número da caixa/pasta.", type="warning")
            return
        try:
            save_record(data, current_id)
        except Exception as error:
            ui.notify(f"Não foi possível salvar: {error}", type="negative")
            return
        close_dialog()
        refresh_table()
        ui.notify("Registro salvo com sucesso.", type="positive")

    def confirm_delete() -> None:
        if current_id is None:
            return
        with ui.dialog() as confirmation:
            with ui.card().classes("w-96"):
                ui.label("Excluir registro?").classes("text-h6")
                ui.label("Esta ação não poderá ser desfeita.").classes("text-gray-600")
                with ui.row().classes("w-full justify-end gap-2 mt-4"):
                    ui.button("Cancelar", on_click=confirmation.close).props("flat")

                    def do_delete() -> None:
                        delete_record(current_id)
                        confirmation.close()
                        close_dialog()
                        refresh_table()
                        ui.notify("Registro excluído.", type="positive")

                    ui.button("Excluir", color="negative", on_click=do_delete)
        confirmation.open()

    def open_form(record: dict[str, Any] | None = None) -> None:
        nonlocal current_id, files_container
        current_id = record["id"] if record else None
        dialog.clear()
        with dialog, ui.card().classes("w-full max-w-5xl"):
            ui.label("Editar arquivo" if record else "Adicionar arquivo").classes("text-h5")
            ui.label("Cadastre cada arquivo com assunto, interessado e link próprio.").classes("text-gray-600 mb-3")

            with ui.column().classes("w-full gap-2"):
                fields["local_arquivo"] = ui.select(
                    ["Caixa de Arquivo Morto", "Pasta Cinza", "Fichario"],
                    label="Local de arquivo",
                    value=(record.get("local_arquivo", "") if record else None),
                ).props("outlined dense")
                with ui.row().classes("w-full gap-2"):
                    fields["numero_caixa_pasta"] = ui.input(
                        "Número da caixa/pasta",
                        value=str(record.get("numero_caixa_pasta", "") if record else ""),
                    ).props("outlined dense").classes("flex-1")

                with ui.row().classes("w-full items-center justify-between mt-2"):
                    ui.label(f"Arquivos contidos (até {MAX_FILES})").classes("text-subtitle1 font-semibold")
                    ui.button("Adicionar arquivo", icon="add", on_click=add_file_field).props("outline dense")
                files_container = ui.column().classes("w-full gap-2 max-h-80 overflow-y-auto")
                rebuild_file_inputs(
                    (record.get("arquivos_contidos", []) if record else [{"numero_envelope": "", "nome": "", "assunto": "", "interessado": "", "link": ""}])
                )

            with ui.row().classes("w-full justify-between mt-4"):
                if record:
                    ui.button("Excluir", icon="delete", color="negative", on_click=confirm_delete).props("outline")
                else:
                    ui.element("div")
                with ui.row().classes("gap-2"):
                    ui.button("Cancelar", on_click=close_dialog).props("flat")
                    ui.button("Salvar", icon="save", color="primary", on_click=save_form)
        dialog.open()

    def handle_double_click(event: Any) -> None:
        args = event.args
        row = None
        if isinstance(args, dict):
            row = args.get("row") or args
        elif isinstance(args, list):
            for value in args:
                if isinstance(value, dict) and ("id" in value or "row" in value):
                    row = value.get("row", value)
                    break
        if row and row.get("id") is not None:
            record = next((item for item in record_table.rows if item["id"] == row["id"]), None)
            if record:
                open_form(record)

    ui.add_head_html("""
        <style>
            body { background: #f5f7fb; }
            .q-table th { font-weight: 700; background: #e8eef7; }
            .q-table tbody tr { cursor: pointer; }
            .q-table tbody tr:hover { background: #eaf2ff !important; }
            .search-highlight { background: #dc2626; color: #ffffff; padding: 1px 3px; border-radius: 3px; font-weight: 700; }
            .search-results-title { font-size: 1.05rem; font-weight: 700; color: #334155; margin: 0.5rem 0; }
            .search-result-card { background: #ffffff; border: 1px solid #cbd5e1; border-left: 5px solid #dc2626; border-radius: 8px; padding: 0.8rem 1rem; margin: 0.6rem 0; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
            .search-result-title { font-weight: 700; color: #991b1b; margin-bottom: 0.35rem; }
            .search-file { margin-top: 0.55rem; padding: 0.5rem; background: #f8fafc; border-radius: 5px; display: grid; gap: 0.15rem; }
        </style>
    """)

    with ui.header().classes("items-center justify-between bg-slate-900 px-6"):
        with ui.row().classes("items-center gap-3"):
            ui.icon("inventory_2", size="32px").classes("text-sky-300")
            ui.label("Arquivos em Geral").classes("text-h5 text-white font-bold")
        ui.label("Controle de caixas, pastas e envelopes").classes("text-slate-200")

    with ui.column().classes("w-full max-w-screen-2xl mx-auto p-6 gap-4"):
        with ui.card().classes("w-full"):
            with ui.row().classes("w-full items-end gap-3"):
                search_input = ui.input(
                    "Buscar por local, caixa/pasta, envelope, arquivo ou link"
                ).props("outlined clearable").classes("flex-1")
                ui.button("Buscar", icon="search", on_click=refresh_table).classes("h-14")
                ui.button("Adicionar registro", icon="add", color="primary", on_click=lambda: open_form()).classes("h-14")
            search_input.on("keydown.enter", refresh_table)

        results_panel = ui.html("").classes("w-full")

        with ui.row().classes("w-full items-center justify-between"):
            total_label = ui.label()
            ui.label("Dica: dê duplo clique em uma linha para editar ou excluir.").classes("text-gray-600")

        record_table = ui.table(
            columns=COLUMNS,
            rows=list_records(),
            row_key="id",
            pagination={"rowsPerPage": 25},
        ).classes("w-full")
        record_table.add_slot(
            "body-cell-local_arquivo",
            """
            <q-td :props="props"><span v-html="props.row.local_html"></span></q-td>
            """,
        )
        record_table.add_slot(
            "body-cell-numero_caixa_pasta",
            """
            <q-td :props="props"><span v-html="props.row.caixa_html"></span></q-td>
            """,
        )
        record_table.add_slot(
            "body-cell-arquivos_contidos",
            """
            <q-td :props="props">
                <div v-for="(arquivo, index) in props.row.arquivos_contidos" :key="index" class="q-mb-sm">
                    <div><strong>{{ index + 1 }}. <span v-html="arquivo.nome_html"></span></strong> — Envelope: <span v-if="arquivo.numero_envelope" v-html="arquivo.numero_envelope_html"></span><span v-else>Não informado</span></div>
                    <div class="text-grey-8">Assunto: <span v-if="arquivo.assunto" v-html="arquivo.assunto_html"></span><span v-else>Não informado</span></div>
                    <div class="text-grey-8">Interessado: <span v-if="arquivo.interessado" v-html="arquivo.interessado_html"></span><span v-else>Não informado</span></div>
                    <a v-if="arquivo.link" :href="arquivo.link" target="_blank" rel="noopener" class="text-blue-700 underline"><span v-html="arquivo.link_html"></span></a>
                    <span v-else class="text-gray-400">Sem link</span>
                </div>
            </q-td>
            """,
        )
        record_table.on("rowDblclick", handle_double_click)
        total_label.set_text(f"{len(record_table.rows)} registro(s) exibido(s)")

    dialog = ui.dialog()


ui.run(title="Arquivos em Geral", host="0.0.0.0", port=PORT, reload=False)
