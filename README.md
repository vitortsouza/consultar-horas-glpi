# Relatórios GLPI (HE/HN)

Script em Python para gerar relatórios de horas a partir da API REST do GLPI:

- **HN**: horas normais da semana atual (segunda a domingo).
- **HE**: horas extras do ciclo mensal 26–25, com estimativa financeira opcional.

## Requisitos

- Python 3.8 ou superior.
- Acesso à API REST do GLPI com `App-Token` e `User-Token` válidos.
- Windows com WSL para usar os arquivos `.bat` (ou execute pelo WSL/Linux diretamente).

## Configuração

1. Copie o arquivo de exemplo:

   ```bash
   cp config.env.example config.env
   ```

2. Edite `config.env` e preencha:

   ```dotenv
   export GLPI_API_URL='https://seu-glpi.exemplo.com/apirest.php'
   export GLPI_APP_TOKEN='seu_app_token'
   export GLPI_USER_TOKEN='seu_user_token'
   export GLPI_TECH_FILTER=''
   export SALARIO_BASE='0'
   ```

   Use aspas simples nos valores, principalmente quando houver espaços (por exemplo, no nome do técnico).

   - `GLPI_TECH_FILTER`: nome do técnico para filtrar. Deixe vazio para incluir todos.
   - `SALARIO_BASE`: salário base usado no cálculo de HE. Use `0` para desativar o cálculo financeiro.
   - Os percentuais e a carga horária já vêm com valores padrão; ajuste se necessário.

3. O arquivo `config.env` contém segredos e **não deve ser commitado**. Ele já está no `.gitignore`.

## Uso

### Windows

- Duplo clique em `run-he.bat` para HE.
- Duplo clique em `run-hn.bat` para HN.
- `HE.bat` e `HN semanal.bat` são mantidos como atalhos de compatibilidade.

### WSL/Linux

```bash
chmod +x run.sh
./run.sh he
./run.sh hn
```

Para depuração:

```bash
./run.sh he --debug
```

### Execução direta

Com as variáveis de ambiente já exportadas:

```bash
python3 glpi_report.py he
python3 glpi_report.py hn
```

## Saída

- **HN**: período, total de tarefas, tarefas HN, total em `HH:MM` e detalhes.
- **HE**: período, total de tarefas, tarefas HE, total em `HH:MM`, estimativa financeira (quando `SALARIO_BASE > 0`) e detalhes.

O número do chamado é exibido quando é possível correlacionar a tarefa com os detalhes retornados pela API; caso contrário, aparece como `N/D`.

## Estrutura

```text
.
├── glpi_report.py          # script principal (he/hn)
├── run.sh                  # carrega config.env e executa o script
├── config.env.example      # modelo de configuração
├── config.env              # configuração local (ignorada pelo Git)
├── run-he.bat              # atalho Windows para HE
├── run-hn.bat              # atalho Windows para HN
├── HE.bat                  # compatibilidade
└── HN semanal.bat          # compatibilidade
```

## Segurança

- Nunca versione `config.env`, tokens ou dados pessoais.
- Se algum token foi exposto, revogue e gere um novo no GLPI.
- Prefira permissões mínimas para o usuário/token usado na API.

## Solução de problemas

- Os `.bat` usam a distribuição WSL padrão. Para fixar outra, edite o comando para `wsl.exe -d NomeDaDistro --cd "%~dp0" -- bash run.sh he`.
- `run.sh` remove automaticamente o `\r` de arquivos `config.env` salvos no Windows.
- Se `config.env` não existir, o script também aceita as variáveis já exportadas no ambiente.
- Em caso de erro HTTP ou de conexão, confira a URL da API, os tokens e o acesso à rede.

## Observações

- O ciclo de HE considera do dia 26 ao dia 25 do mês seguinte, com fim exclusivo.
- A semana de HN considera segunda-feira como início e a segunda seguinte como fim exclusivo.
- O cálculo financeiro é uma estimativa simplificada; a folha real pode variar por regras progressivas, adicionais e eventos do mês.
