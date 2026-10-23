#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import unicodedata
from datetime import date, datetime, timedelta
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def read_float(name, default):
    raw = os.getenv(name, default)
    try:
        return float(str(raw).replace(',', '.'))
    except ValueError:
        raise SystemExit(f'Erro: {name} deve ser um numero.')


API_URL = os.getenv('GLPI_API_URL', '').strip().rstrip('/')
APP_TOKEN = (os.getenv('GLPI_APP_TOKEN') or os.getenv('GLPI_APP_API_VALUE') or '').strip()
USER_TOKEN = (os.getenv('GLPI_USER_TOKEN') or os.getenv('GLPI_USER_API_VALUE') or '').strip()
TECH_FILTER = os.getenv('GLPI_TECH_FILTER', '').strip()
SALARIO_BASE = read_float('SALARIO_BASE', '0')
CARGA_HORARIA_MENSAL = read_float('CARGA_HORARIA_MENSAL', '220')
PERCENTUAL_HE = read_float('PERCENTUAL_HE', '0.50')
PERCENTUAL_DSR_HE = read_float('PERCENTUAL_DSR_HE', '0.1538461538')
PERCENTUAL_INSS = read_float('PERCENTUAL_INSS', '0.1110')
PERCENTUAL_IRRF = read_float('PERCENTUAL_IRRF', '0.2750')
PAGE_SIZE = 100
DEBUG = (
    os.getenv('DEBUG_GLPI', '0') == '1'
    or os.getenv('DEBUG_GLPI_HE', '0') == '1'
    or os.getenv('DEBUG_GLPI_HN', '0') == '1'
)

SEARCH_FIELD = {
    'taskDescription': '1',
    'taskCategory': '2',
    'taskDate': '3',
    'analyst': '5',
    'actiontime': '6',
    'taskState': '7',
}


def validate_config():
    missing = []

    if not API_URL:
        missing.append('GLPI_API_URL')
    if not APP_TOKEN:
        missing.append('GLPI_APP_TOKEN')
    if not USER_TOKEN:
        missing.append('GLPI_USER_TOKEN')

    if missing:
        print('Erro: defina ' + ', '.join(missing) + ' no ambiente ou no config.env.', file=sys.stderr)
        sys.exit(1)

    if SALARIO_BASE > 0 and CARGA_HORARIA_MENSAL <= 0:
        print('Erro: CARGA_HORARIA_MENSAL deve ser maior que zero quando SALARIO_BASE > 0.', file=sys.stderr)
        sys.exit(1)


def debug(msg):
    if DEBUG:
        print(f'[DEBUG] {msg}', file=sys.stderr)


def normalize_text(value):
    text = unescape(str(value or ''))
    text = re.sub(r'<[^>]*>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip().lower()
    text = unicodedata.normalize('NFKD', text)
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    return text


def clean_text(value):
    text = unescape(str(value or ''))
    text = re.sub(r'<[^>]*>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def normalize_name_for_match(value):
    text = normalize_text(value)
    text = text.replace('.', ' ')
    text = text.replace('@', ' ')
    text = re.sub(r'[^a-z0-9]+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def current_cycle_period(ref_date=None):
    today = ref_date or date.today()

    if today.day >= 26:
        start = date(today.year, today.month, 26)
        if today.month == 12:
            end = date(today.year + 1, 1, 26)
        else:
            end = date(today.year, today.month + 1, 26)
    else:
        if today.month == 1:
            start = date(today.year - 1, 12, 26)
        else:
            start = date(today.year, today.month - 1, 26)
        end = date(today.year, today.month, 26)

    return start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')


def current_week_period(ref_date=None):
    today = ref_date or datetime.now().date()
    monday = today - timedelta(days=today.weekday())
    next_monday = monday + timedelta(days=7)
    return monday.strftime('%Y-%m-%d'), next_monday.strftime('%Y-%m-%d')


def shift_datetime_str(value, seconds):
    dt = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
    dt = dt + timedelta(seconds=seconds)
    return dt.strftime('%Y-%m-%d %H:%M:%S')


def period_bounds(report):
    if report == 'hn':
        start_date, end_date = current_week_period()
    else:
        start_date, end_date = current_cycle_period()

    start_dt = f'{start_date} 00:00:00'
    end_dt = f'{end_date} 00:00:00'
    start_boundary = shift_datetime_str(start_dt, -1)
    return start_date, end_date, start_dt, end_dt, start_boundary


def request_json(path, headers, params=None):
    url = API_URL + path
    if params:
        url += '?' + urlencode(params)
    req = Request(url, headers=headers, method='GET')
    with urlopen(req, timeout=60) as resp:
        raw = resp.read().decode('utf-8', errors='replace')
        return json.loads(raw)


def init_session():
    headers = {
        'Content-Type': 'application/json',
        'App-Token': APP_TOKEN,
        'Authorization': f'user_token {USER_TOKEN}',
    }
    data = request_json('/initSession', headers)
    token = data.get('session_token') if isinstance(data, dict) else None

    if not token:
        message = data.get('message') if isinstance(data, dict) else ''
        detail = f' {message}' if message else ''
        raise RuntimeError(f'Falha ao abrir sessão no GLPI.{detail}')

    return token


def kill_session(session_token):
    headers = {
        'Content-Type': 'application/json',
        'App-Token': APP_TOKEN,
        'Session-Token': session_token,
    }
    try:
        request_json('/killSession', headers)
    except Exception:
        pass


def fetch_tasks(session_token, start_boundary, end_dt):
    headers = {
        'Content-Type': 'application/json',
        'App-Token': APP_TOKEN,
        'Session-Token': session_token,
    }
    all_rows = []
    offset = 0

    while True:
        params = {
            'criteria[0][field]': SEARCH_FIELD['taskDate'],
            'criteria[0][searchtype]': 'morethan',
            'criteria[0][value]': start_boundary,
            'criteria[1][link]': 'AND',
            'criteria[1][field]': SEARCH_FIELD['taskDate'],
            'criteria[1][searchtype]': 'lessthan',
            'criteria[1][value]': end_dt,
            'forcedisplay[0]': SEARCH_FIELD['taskDescription'],
            'forcedisplay[1]': SEARCH_FIELD['taskCategory'],
            'forcedisplay[2]': SEARCH_FIELD['taskDate'],
            'forcedisplay[3]': SEARCH_FIELD['analyst'],
            'forcedisplay[4]': SEARCH_FIELD['actiontime'],
            'forcedisplay[5]': SEARCH_FIELD['taskState'],
            'range': f'{offset}-{offset + PAGE_SIZE - 1}',
        }
        data = request_json('/search/TicketTask', headers, params)
        rows = data.get('data', [])
        all_rows.extend(rows)
        debug(f'search/TicketTask offset={offset} rows={len(rows)} total={len(all_rows)}')

        if len(rows) < PAGE_SIZE:
            break

        offset += PAGE_SIZE

    return all_rows


def fetch_tickettask_details(session_token, start_dt, end_dt):
    headers = {
        'Content-Type': 'application/json',
        'App-Token': APP_TOKEN,
        'Session-Token': session_token,
    }
    details = []
    offset = 0
    stop = False

    while not stop:
        params = {
            'range': f'{offset}-{offset + PAGE_SIZE - 1}',
            'sort': 'date',
            'order': 'DESC',
        }
        rows = request_json('/TicketTask', headers, params)

        if not isinstance(rows, list) or not rows:
            break

        added = 0
        for row in rows:
            task_date = str(row.get('date', ''))
            if start_dt <= task_date < end_dt:
                details.append(row)
                added += 1
            elif task_date and task_date < start_dt:
                stop = True

        debug(f'/TicketTask offset={offset} rows={len(rows)} added={added} total_details={len(details)} stop={stop}')

        if len(rows) < PAGE_SIZE:
            break

        offset += PAGE_SIZE

    return details


def to_seconds(value):
    if value in (None, ''):
        return 0
    if isinstance(value, (int, float)):
        return int(value)

    text = str(value).strip()

    if text.isdigit():
        return int(text)

    match = re.match(r'^(\d{1,3}):(\d{2})(?::(\d{2}))?$', text)
    if match:
        hours, minutes, seconds = match.groups()
        return int(hours) * 3600 + int(minutes) * 60 + int(seconds or 0)

    return 0


def hhmm(seconds):
    total = max(0, int(seconds))
    hours = total // 3600
    minutes = (total % 3600) // 60
    return f'{hours:02d}:{minutes:02d}'


def money(value):
    text = f'{value:,.2f}'
    return text.replace(',', 'X').replace('.', ',').replace('X', '.')


def is_he(category):
    cat = normalize_text(category).upper()
    return cat.startswith('HE') or '»HE' in cat


def is_hn(category):
    cat = normalize_text(category).upper()
    return cat.startswith('HN') or '»HN' in cat


def get_field(row, uid_key, numeric_key):
    value = row.get(uid_key)
    if value not in (None, ''):
        return value
    return row.get(numeric_key, '')


def tech_matches(value, tech_filter):
    candidate = normalize_name_for_match(value)
    wanted = normalize_name_for_match(tech_filter)

    if not wanted:
        return True
    if wanted in candidate:
        return True

    wanted_tokens = wanted.split()
    candidate_tokens = candidate.split()
    return all(token in candidate_tokens for token in wanted_tokens)


def normalize_search_rows(rows, tech_filter):
    normalized = []

    for row in rows:
        tecnico = get_field(row, 'TicketTask.User.name', '5')
        item = {
            'descricao': clean_text(get_field(row, 'TicketTask.content', '1')),
            'categoria': str(get_field(row, 'TicketTask.TaskCategory.name', '2')),
            'data': str(get_field(row, 'TicketTask.date', '3')),
            'tecnico': str(tecnico),
            'segundos': to_seconds(get_field(row, 'TicketTask.actiontime', '6')),
            'status': str(get_field(row, 'TicketTask.state', '7')),
            'chamado': 'N/D',
        }
        if tech_matches(tecnico, tech_filter):
            normalized.append(item)

    debug(f'normalize_search_rows total_in={len(rows)} total_out={len(normalized)}')
    return normalized


def build_detail_index(detail_rows):
    index = {}

    for row in detail_rows:
        task_date = str(row.get('date', ''))
        seconds = to_seconds(row.get('actiontime', 0))
        content = clean_text(row.get('content', ''))
        ticket_id = str(row.get('tickets_id') or '').strip() or 'N/D'
        keys = [
            (task_date, seconds, normalize_text(content[:120])),
            (task_date, seconds, normalize_text(content[:80])),
            (task_date, seconds, normalize_text(content[:40])),
        ]
        for key in keys:
            index.setdefault(key, []).append(ticket_id)

    debug(f'build_detail_index keys={len(index)} detail_rows={len(detail_rows)}')
    return index


def attach_ticket_numbers(search_rows, detail_index):
    matched = 0

    for item in search_rows:
        desc = clean_text(item['descricao'])
        keys = [
            (item['data'], item['segundos'], normalize_text(desc[:120])),
            (item['data'], item['segundos'], normalize_text(desc[:80])),
            (item['data'], item['segundos'], normalize_text(desc[:40])),
        ]
        for key in keys:
            matches = detail_index.get(key, [])
            if matches:
                item['chamado'] = matches.pop(0)
                matched += 1
                break

    debug(f'attach_ticket_numbers matched={matched} total={len(search_rows)}')
    return search_rows


def calcular_financeiro(total_he_segundos):
    horas_extras = total_he_segundos / 3600.0
    valor_hora = SALARIO_BASE / CARGA_HORARIA_MENSAL
    valor_he = horas_extras * valor_hora * (1.0 + PERCENTUAL_HE)
    valor_reflexo_dsr = valor_he * PERCENTUAL_DSR_HE
    bruto_estimado = valor_he + valor_reflexo_dsr
    desconto_inss = bruto_estimado * PERCENTUAL_INSS
    desconto_irrf = bruto_estimado * PERCENTUAL_IRRF
    liquido_estimado = bruto_estimado - desconto_inss - desconto_irrf
    return {
        'horas_extras': horas_extras,
        'valor_hora': valor_hora,
        'valor_he': valor_he,
        'valor_reflexo_dsr': valor_reflexo_dsr,
        'bruto_estimado': bruto_estimado,
        'desconto_inss': desconto_inss,
        'desconto_irrf': desconto_irrf,
        'liquido_estimado': liquido_estimado,
    }


def print_hn_report(rows, start_date, end_date, tech_filter):
    hn_rows = [row for row in rows if is_hn(row['categoria'])]
    total_hn = sum(row['segundos'] for row in hn_rows)

    print('=' * 90)
    print('RELATÓRIO GLPI - HN DA SEMANA ATUAL')
    print('=' * 90)
    print(f'Período        : {start_date} até {end_date} (fim exclusivo)')
    print(f'Filtro técnico : {tech_filter or "Todos"}')
    print(f'Total tarefas  : {len(rows)}')
    print(f'Tarefas HN     : {len(hn_rows)}')
    print(f'Total HN       : {hhmm(total_hn)}')
    print(f'Total HN (seg) : {total_hn}')
    print('-' * 90)

    if hn_rows:
        print('Detalhes HN:')
        for row in sorted(hn_rows, key=lambda item: (item['data'], item['categoria'], item['segundos'])):
            desc = row['descricao'][:100]
            print(f"- {row['data']} | {hhmm(row['segundos'])} | {row['categoria']} | {row['chamado']} | {desc}")
    else:
        print('Nenhuma tarefa HN encontrada para o filtro informado.')

    print('=' * 90)


def print_he_report(rows, start_date, end_date, tech_filter):
    he_rows = [row for row in rows if is_he(row['categoria'])]
    total_he = sum(row['segundos'] for row in he_rows)

    print('=' * 96)
    print('RELATÓRIO GLPI - HE DO CICLO MENSAL 26-25')
    print('=' * 96)
    print(f'Período              : {start_date} até {end_date} (fim exclusivo)')
    print(f'Filtro técnico       : {tech_filter or "Todos"}')
    print(f'Total tarefas        : {len(rows)}')
    print(f'Tarefas HE           : {len(he_rows)}')
    print(f'Total HE             : {hhmm(total_he)}')
    print(f'Total HE (seg)       : {total_he}')
    print('-' * 96)

    if SALARIO_BASE > 0:
        financeiro = calcular_financeiro(total_he)
        print(f'Salário base         : R$ {money(SALARIO_BASE)}')
        print(f'Carga horária mensal : {CARGA_HORARIA_MENSAL:.2f} h')
        print(f'Valor hora           : R$ {money(financeiro["valor_hora"])}')
        print(f'Valor HE bruto       : R$ {money(financeiro["valor_he"])}')
        print(f'Reflexo DSR estimado : R$ {money(financeiro["valor_reflexo_dsr"])}')
        print(f'Total bruto estimado : R$ {money(financeiro["bruto_estimado"])}')
        print(f'INSS estimado        : R$ {money(financeiro["desconto_inss"])} ({PERCENTUAL_INSS * 100:.2f}%)')
        print(f'IRRF estimado        : R$ {money(financeiro["desconto_irrf"])} ({PERCENTUAL_IRRF * 100:.2f}%)')
        print(f'Total líquido est.   : R$ {money(financeiro["liquido_estimado"])}')
    else:
        print('Salário base         : não configurado')
        print('Cálculo financeiro   : omitido (defina SALARIO_BASE no config.env)')

    print('-' * 96)

    if he_rows:
        print('Detalhes HE:')
        for row in sorted(he_rows, key=lambda item: (item['data'], item['categoria'], item['segundos'])):
            desc = row['descricao'][:100]
            print(f"- {row['data']} | {hhmm(row['segundos'])} | {row['categoria']} | {row['chamado']} | {desc}")
    else:
        print('Nenhuma tarefa HE encontrada para o filtro informado.')

    print('=' * 96)

    if SALARIO_BASE > 0:
        print('Observação: o cálculo líquido é uma estimativa simplificada sobre o bruto de HE + reflexo DSR.')
        print('A folha real pode variar por base progressiva, adicional noturno, outros eventos e regras do mês.')
        print('=' * 96)


def parse_args():
    parser = argparse.ArgumentParser(
        description='Gera relatórios de HE ou HN a partir da API do GLPI.'
    )
    parser.add_argument(
        'report',
        choices=('he', 'hn'),
        help='he: ciclo mensal 26-25; hn: semana atual.',
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Exibe mensagens de depuração.',
    )
    return parser.parse_args()


def main():
    global DEBUG

    args = parse_args()
    if args.debug:
        DEBUG = True

    validate_config()
    start_date, end_date, start_dt, end_dt, start_boundary = period_bounds(args.report)
    session_token = None

    try:
        session_token = init_session()
        search_rows = fetch_tasks(session_token, start_boundary, end_dt)
        normalized = normalize_search_rows(search_rows, TECH_FILTER)
        detail_rows = fetch_tickettask_details(session_token, start_dt, end_dt)
        detail_index = build_detail_index(detail_rows)
        enriched = attach_ticket_numbers(normalized, detail_index)

        if args.report == 'hn':
            print_hn_report(enriched, start_date, end_date, TECH_FILTER)
        else:
            print_he_report(enriched, start_date, end_date, TECH_FILTER)
    except HTTPError as exc:
        print(f'Erro HTTP {exc.code}: {exc.reason}', file=sys.stderr)
        sys.exit(1)
    except URLError as exc:
        print(f'Erro de conexão: {exc.reason}', file=sys.stderr)
        sys.exit(1)
    except (RuntimeError, ValueError) as exc:
        print(f'Erro: {exc}', file=sys.stderr)
        sys.exit(1)
    finally:
        if session_token:
            kill_session(session_token)


if __name__ == '__main__':
    main()
