import asyncio
from os import system
from time import time

from git import Repo
from git.exc import GitCommandError

from userge import Config, Message, pool, userge

LOG = userge.getLogger(__name__)
CHANNEL = userge.getCLogger(__name__)


@userge.on_cmd(
    "atualizar",
    about={
        "header": "Verifica atualizações ou simplesmente atualiza o AppleBot",
        "flags": {
            "-buscar": "buscar atualizações",
            "-branch": "O padrão é -alpha",
        },
        "como usar": (
            "{tr}atualizar: verifica as atualizações disponíveis no branch padrão\n"
            "{tr}atualizar -[branch_name] : verifica atualizações de qualquer branch\n"
            "add -buscar se você quiser obter as atualizações\n"
        ),
        "exemplo": "{tratualizar -buscar",
    },
    del_pre=True,
    allow_channels=False,
)
async def check_update(message: Message):
    """Verifica ou Atualiza"""
    await message.edit("`Verificando se há atualizações disponíveis, aguarde....`")
    if Config.HEROKU_ENV:
        await message.edit(
            "**Heroku App detectado.** Por segurança, as atualizações foram desativas.\n"
            "Seu bot será atualizado automaticamente quando você simplesmente reiniciar o Heroku."
        )
        return
    flags = list(message.flags)
    pull_from_repo = False
    push_to_heroku = False
    branch = "alpha"
    if "buscar" in flags:
        pull_from_repo = True
        flags.remove("pull")
    if "enviar" in flags:
        if not Config.HEROKU_APP:
            await message.err("App do Heroku não foi encontrado!")
            return
        # push_to_heroku = True
        # flags.remove("push")
    if len(flags) == 1:
        branch = flags[0]
    repo = Repo()
    if branch not in repo.branches:
        await message.err(f"Nome do branch é inválido: {branch}")
        return
    try:
        out = _get_updates(repo, branch)
    except GitCommandError as g_e:
        if "128" in str(g_e):
            system(
                f"git fetch {Config.UPSTREAM_REMOTE} {branch} && git checkout -f {branch}"
            )
            out = _get_updates(repo, branch)
        else:
            await message.err(g_e, del_in=5)
            return
    if not (pull_from_repo or push_to_heroku):
        if out:
            change_log = f"**Uma nova atualização está disponível em [{branch}]:\n\n📄 LISTA DE MUDANÇAS 📄**\n\n"
            await message.edit_or_send_as_file(
                change_log + out, disable_web_page_preview=True
            )
        else:
            await message.edit(f"**AppleBot está atualizado em [{branch}]**", del_in=5)
        return
    if pull_from_repo:
        if out:
            await message.edit(
                f"`Nova atualização encontrada em [{branch}], Buscando atualização...`"
            )
            await _pull_from_repo(repo, branch)
            await CHANNEL.log(
                f"**Atualização encontrada em [{branch}]:\n\n📄 LISTA DE MUDANÇAS 📄**\n\n{out}"
            )
            if not push_to_heroku:
                await message.edit(
                    "**AppleBot foi atualizado perfeitamente!**\n"
                    "`Reiniiciando... espere um pouco, tá bom?`",
                    del_in=3,
                )
                asyncio.get_event_loop().create_task(userge.restart(True))
        elif push_to_heroku:
            await _pull_from_repo(repo, branch)
        else:
            active = repo.active_branch.name
            if active == branch:
                await message.err(f"Já está em [{branch}]!")
                return
            await message.edit(
                f"`Alternando HEAD de [{active}] >>> [{branch}] ...`", parse_mode="md"
            )
            await _pull_from_repo(repo, branch)
            await CHANNEL.log(f"`Alterado HEAD de [{active}] >>> [{branch}] !`")
            await message.edit("``Reiniiciando... espere um pouco, tá bom?`", del_in=3)
            asyncio.get_event_loop().create_task(userge.restart())
    if push_to_heroku:
        await _push_to_heroku(message, repo, branch)


def _get_updates(repo: Repo, branch: str) -> str:
    repo.remote(Config.UPSTREAM_REMOTE).fetch(branch)
    upst = Config.UPSTREAM_REPO.rstrip("/")
    out = ""
    upst = Config.UPSTREAM_REPO.rstrip("/")
    for i in repo.iter_commits(f"HEAD..{Config.UPSTREAM_REMOTE}/{branch}"):
        out += f"🔨 **#{i.count()}** : [{i.summary}]({upst}/commit/{i}) 👷 __{i.author}__\n\n"
    return out


async def _pull_from_repo(repo: Repo, branch: str) -> None:
    repo.git.checkout(branch, force=True)
    repo.git.reset("--hard", branch)
    repo.remote(Config.UPSTREAM_REMOTE).pull(branch, force=True)
    await asyncio.sleep(1)


async def _push_to_heroku(msg: Message, repo: Repo, branch: str) -> None:
    sent = await msg.edit(
        f"`Enviandos atualizações de [{branch}] para o Heroku...\n"
        "Este processa leva em média de 5min.`\n\n"
        f"* **Reinicia** após 5min usando `{Config.CMD_TRIGGER}ree -apple -apple`\n\n"
        "* Após reiniciar, verifique se tudo ocorreu bem. :)"
    )
    try:
        await _heroku_helper(sent, repo, branch)
    except GitCommandError as g_e:
        LOG.exception(g_e)
    else:
        await sent.edit(
            f"**Aplicativo do Heroku: {Config.HEROKU_APP.name} está atualizado na branch [{branch}]**"
        )


@pool.run_in_thread
def _heroku_helper(sent: Message, repo: Repo, branch: str) -> None:
    start_time = time()
    edited = False

    def progress(op_code, cur_count, max_count=None, message=""):
        nonlocal start_time, edited
        prog = f"**code:** `{op_code}` **cur:** `{cur_count}`"
        if max_count:
            prog += f" **max:** `{max_count}`"
        if message:
            prog += f" || `{message}`"
        LOG.debug(prog)
        now = time()
        if not edited or (now - start_time) > 3 or message:
            edited = True
            start_time = now
            userge.loop.create_task(sent.try_to_edit(f"{cur_msg}\n\n{prog}"))

    cur_msg = sent.text.html
    repo.remote("heroku").push(
        refspec=f"{branch}:master", progress=progress, force=True
    )
