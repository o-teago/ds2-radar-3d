# DS2 Radar 3D

Um radar 3D em tempo real para **Dark Souls II: Scholar of the First Sin** num
**PS4 desbloqueado**. Ele lê a sua posição ao vivo da memória do jogo e mostra
você sobre a geometria 3D real dos mapas, no navegador.

- Posição do player ao vivo + trilha
- Troca de área automática (carrega o mapa certo conforme você anda)
- Mundo inteiro (as 24 áreas de uma vez) ou dinâmico (só as próximas)
- Câmera livre: orbitar, arrastar, zoom, e modo noclip (voar)
- Modo "alinhar ao movimento", painel de ligar/desligar áreas, exportar trilha (CSV)

> ⚠️ Ferramenta somente-leitura, para uso pessoal/offline. Não use online.

---

## Status & compatibilidade

Este é o release **v1.0** da comunidade. Está **totalmente testado e confirmado
funcionando no Dark Souls II: Scholar of the First Sin — CUSA01760, patch 1.02**
(a versão para a qual o `config.ini` incluso foi validado). Nessa versão tudo
funciona perfeitamente.

**NÃO testamos nenhuma outra versão, região ou patch.** Em especial:

- As ferramentas **finder** (`finder/`) *deveriam* gerar um config funcional para
  outras builds, mas não verificamos isso em mais nada.
- A **geometria dos mapas** *deveria* ser idêntica entre versões, mas também não
  verificamos.

Então, em outra build, trate como **experimental — teste você mesmo**. Se
funcionar, compartilhe seu `config.ini` (com o CUSA + patch) pra ajudar os outros.

---

## Screenshots

![Majula em 3D com a posição ao vivo](screenshots/radar-majula.png)
*Posição ao vivo (ponto vermelho) e trilha sobre a geometria 3D real de Majula.*

![Perfil lateral de Majula](screenshots/radar-profile.png)
*Câmera livre — orbitar, arrastar e dar zoom no mapa em qualquer ângulo.*

![Troca de área automática](screenshots/radar-multiarea.png)
*Dois mapas conectados carregados conforme você anda entre as áreas.*

---

## Requisitos

**PS4 (desbloqueado, GoldHEN):**
- O payload **ps4debug**. É padrão num PS4 desbloqueado e há várias formas de
  enviar (menus de payload / GoldHEN / um homebrew que envia payloads). Pesquise
  **"carregar payload ps4debug GoldHEN"**. Use a build que combina com o seu
  firmware (ex.: a build ctn123 & SiSTRo para FW 9.00). **Essa etapa é
  obrigatória** — o radar fala com o PS4 através do ps4debug.

**PC:**
- Python 3.9+  ·  `pip install -r requirements.txt`  (ps4debug, websockets, numpy)
- Um navegador moderno.

---

## Preparação (uma vez)

1. Instale as dependências do Python:
   ```
   pip install -r requirements.txt
   ```
2. Abra o **`config.ini`** e ponha o IP do seu PS4:
   ```
   [ps4]
   ip = 192.168.1.104
   ```
   O resto do `config.ini` já vem preenchido e validado para
   **Dark Souls II SotFS, CUSA01760, patch 1.02**. Se o seu jogo for outra
   versão, veja [Outra versão](#outra-versao) abaixo.

## Uso (toda vez)

3. No PS4, **carregue o payload ps4debug** (veja Requisitos).
4. **Abra o jogo** e carregue o seu save.
5. No PC, inicie o server:
   ```
   python server.py
   ```
6. Abra **http://localhost:8080/radar.html** no navegador.

Posição e área aparecem sozinhas, e continuam funcionando mesmo depois de
reiniciar o jogo (a posição usa uma cadeia de ponteiro estática). Mantenha o
**PS4CheaterNeo fechado** enquanto o server ou as ferramentas finder rodam.

---

## Outra versão

A geometria dos mapas é igual pra todo mundo, mas os **offsets de memória** mudam
por build. Gere um `config.ini` novo com a finder (dois estágios, porque um
reboot é o que prova que a cadeia de ponteiro é permanente):

1. **Estágio 1** — jogo aberto, parado em **Majula**:
   ```
   python finder/finder_scan.py
   ```
   Siga os passos na tela: fique parado, dê uns passos, continue andando (acha a
   posição); capture a área atual, viaje para uma segunda área e capture (acha os
   nomes de área); aí ele roda o pointer scan. Salva `finder_state.json`.
2. **Reinicie o jogo.**
3. **Estágio 2** — depois do reboot, numa área aberta:
   ```
   python finder/finder_validate.py
   ```
   Ande em círculos quando pedir. Ele escreve **`config.generated.ini`** nesta pasta.
4. Renomeie `config.generated.ini` para `config.ini` (substituindo o antigo) e
   ponha o seu CUSA/patch na seção `[info]`.

Se o estágio 2 disser "0 chains tracked", refaça o estágio 1 e tente de novo.

---

## Controles (no navegador)

- **Arrastar esquerdo** orbitar · **Direito / Meio / Shift+Esquerdo** arrastar mapa · **Scroll** zoom
- **F** seguir · **L** alinhar ao movimento · **N** noclip (WASD/QE pra voar, Shift = rápido)
- **M** trocar modo (Dinâmico / Mundo inteiro) · **T** trilha · **[ ]** tamanho da bola
- Os chips embaixo mostram o estado (verde = ON). O botão **? shortcuts** lista tudo.
- No modo "Mundo inteiro": painel **Areas** pra ligar/desligar/isolar mapas,
  **Clear trail** e **Export trail** (CSV com X,Y,Z reais do jogo).

---

## Estrutura do projeto

```
server.py            Backend: lê a memória do PS4, serve a página, WebSocket. Rode este.
radar.html           O radar 3D (front-end Three.js)
three.min.js         Three.js (embutido, offline)
config.ini           Offsets por-versão (cadeia da posição + área). Ponha seu IP aqui.
maps/                Geometria — areas.json + <area>_v.bin / _i.bin (igual em toda versão)
finder/              Gera o config.ini pra outra versão (finder_scan.py, finder_validate.py)
tools/               Peças cruas (achador de posição, pointer scan, dump de mapa…)
screenshots/         Imagens usadas neste README
```

---

## Como funciona (resumo)

- **Posição:** uma cadeia de ponteiro estática ancorada nos dados do eboot
  (`base = *( *(eboot_base + static_off) + off0 ) + off1 …`) resolve para um bloco
  `[1.0, X, Y, Z]`. É resolvida a cada tick, então segue as realocações de memória
  do jogo e sobrevive a reboots.
- **Área:** o jogo guarda o nome do mapa atual em ASCII (`"10_04"`) nos dados
  estáticos do eboot; o server lê e a página carrega a malha correspondente.
- **Geometria:** decodificada dos arquivos `.iv` do map-viewer `dks2mv`. O
  transform memória↔malha é uma simples troca X↔Z.

---

## Como começou

O projeto começou como um simples **minimapa 2D**. O problema: conseguir uma
imagem de mapa 2D que batesse com as coordenadas reais do jogo era um pesadelo —
os mapas que a gente achava nunca alinhavam com o mundo. Aí encontramos o
**modelo 3D dos mapas do jogo** (a geometria do map-viewer `dks2mv`), e tudo se
encaixou: em vez de brigar com uma imagem plana, dava pra colocar o player direto
sobre a geometria 3D real. Esse desvio transformou um minimapa simples neste radar
3D completo.

## Contribuindo

Projeto open source e comunitário — contribuições são bem-vindas! Seja um
**config.ini de outra versão/região** do jogo (compartilhe com o CUSA + patch),
correções de bugs ou novas features, fique à vontade pra abrir uma issue ou um PR.

## Créditos

- **dks2mv — Dark Souls Map Viewer** — a geometria `.iv` dos mapas que forma o mundo 3D.
- **ps4debug** (jogolden) e a build para FW 9.00 do **ctn123 & SiSTRo** — acesso à memória do PS4.
- **Biblioteca Python `ps4debug`** — a ponte no lado do PC usada pelo server.
- **GoldHEN** — o ambiente de jailbreak / payload.
- **Three.js** — renderização 3D no navegador.
- **DS2S-META** (Nordgaren) — referência para a pesquisa de memória do Dark Souls II.
- **Dark Souls II: Scholar of the First Sin** © FromSoftware / Bandai Namco.
  Ferramenta fan-made não-oficial, sem afiliação ou endosso.

## Licença

MIT — veja [LICENSE](LICENSE). Faça o que quiser, só mantenha o aviso.
