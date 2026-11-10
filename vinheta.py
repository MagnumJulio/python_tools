#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gera a vinheta de encerramento (1080x1920) com QR Code Pix valido.
Edite o bloco CONFIG e rode: python3 vinheta.py
"""
import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import segno

BASE = os.path.dirname(os.path.abspath(__file__))

def caminho(p):
    """Resolve caminhos relativos a partir da pasta do script."""
    return p if os.path.isabs(p) else os.path.join(BASE, p)

# ----------------------------- CONFIG ---------------------------------------
CFG = dict(
    # --- dados do Pix (o QR e gerado a partir daqui, entao tem que estar certo)
    chave_pix      = "+5521993311216",   # celular no formato +55DDNUMERO
    chave_exibida  = "(21) 99331-1216",  # como aparece escrito na tela
    nome_recebedor = "Valdir Moreira",   # max 25 caracteres
    cidade         = "RIO DE JANEIRO",   # max 15 caracteres
    valor          = None,                # ex: 140.00 para QR de valor fixo; None = valor livre
    descricao      = None,                # ex: "Cesta basica"

    # --- textos
    nome_obra   = "Mission\u00e1rios De N. Sra. e S\u00e3o Bruno",
    lema        = "\u201cVivemos pobres, com os pobres e para os pobres\u201d",
    chamada     = "UMA CESTA B\u00c1SICA CUSTA",
    valor_texto = "R$ 140",
    sub         = "Doe uma cesta por m\u00eas e alimente uma fam\u00edlia",
    rodape      = "@ifmdenossasenhora",
    bencao      = "Deus aben\u00e7oe",

    logo = "uploads/0.png",
    out  = "outputs/vinheta_final_1080x1920.png",
    W = 1080, H = 1920,
)

AZUL_ESC = (44, 82, 130)     # #2c5282
AZUL     = (74, 144, 226)    # #4a90e2
BRANCO   = (255, 255, 255)

# ------------------------------ FONTES --------------------------------------
# Resolve em 3 niveis: pasta local "fontes/" -> download do Google Fonts ->
# fonte equivalente ja instalada no sistema (Windows/macOS/Linux).
import urllib.request

PASTA_FONTES = caminho("fontes")

GOOGLE = "https://raw.githubusercontent.com/google/fonts/main/ofl/"
BAIXAR = {
    "Poppins-Bold.ttf":         GOOGLE + "poppins/Poppins-Bold.ttf",
    "Poppins-Medium.ttf":       GOOGLE + "poppins/Poppins-Medium.ttf",
    "Poppins-Regular.ttf":      GOOGLE + "poppins/Poppins-Regular.ttf",
    "Lora-Italic-Variable.ttf": GOOGLE + "lora/Lora-Italic%5Bwght%5D.ttf",
}
ALTERNATIVAS = {
    "Poppins-Bold.ttf":         ["segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"],
    "Poppins-Medium.ttf":       ["segoeuisl.ttf", "segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"],
    "Poppins-Regular.ttf":      ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"],
    "Lora-Italic-Variable.ttf": ["georgiai.ttf", "timesi.ttf", "ariali.ttf", "DejaVuSerif-Italic.ttf"],
}

_cache_fontes = {}

def _arquivo_da_fonte(nome):
    if nome in _cache_fontes:
        return _cache_fontes[nome]

    local = os.path.join(PASTA_FONTES, nome)
    if not os.path.exists(local) and nome in BAIXAR:
        try:
            os.makedirs(PASTA_FONTES, exist_ok=True)
            print(f"  baixando {nome} ...")
            req = urllib.request.Request(BAIXAR[nome], headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r, open(local, "wb") as f:
                f.write(r.read())
        except Exception as e:
            print(f"  [aviso] nao baixei {nome} ({e}); tentando fonte do sistema")

    for c in [local] + ALTERNATIVAS.get(nome, []) + [nome]:
        try:
            ImageFont.truetype(c, 12)
            _cache_fontes[nome] = c
            return c
        except OSError:
            continue

    print(f"  [aviso] nenhuma fonte encontrada para {nome}; usando a padrao do Pillow")
    _cache_fontes[nome] = None
    return None

def F(name, size):
    c = _arquivo_da_fonte(name)
    return ImageFont.load_default() if c is None else ImageFont.truetype(c, size)

def F_cabe(name, size, txt, largura_max, spacing=0, size_min=20):
    """Igual a F(), mas reduz o corpo ate o texto caber em largura_max."""
    while size > size_min:
        f = F(name, size)
        w = sum(f.getlength(ch) + spacing for ch in txt) - spacing if spacing else f.getlength(txt)
        if w <= largura_max:
            return f
        size -= 1
    return F(name, size_min)

# ------------------------- PIX BR CODE (EMV) --------------------------------
def _tlv(tag, value):
    return f"{tag}{len(value):02d}{value}"

def _crc16(payload: str) -> str:
    crc = 0xFFFF
    for b in payload.encode("utf-8"):
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return f"{crc:04X}"

def brcode(chave, nome, cidade, valor=None, descricao=None, txid="***"):
    mai = _tlv("00", "BR.GOV.BCB.PIX") + _tlv("01", chave)
    if descricao:
        mai += _tlv("02", descricao[:40])
    p  = _tlv("00", "01")
    p += _tlv("26", mai)
    p += _tlv("52", "0000")
    p += _tlv("53", "986")
    if valor is not None:
        p += _tlv("54", f"{valor:.2f}")
    p += _tlv("58", "BR")
    p += _tlv("59", nome[:25])
    p += _tlv("60", cidade[:15])
    p += _tlv("62", _tlv("05", txid))
    p += "6304"
    return p + _crc16(p)

# ------------------------------ helpers -------------------------------------
def texto(d, xy, txt, font, fill, anchor="mm", spacing=0):
    if spacing:
        w = sum(font.getlength(c) + spacing for c in txt) - spacing
        x = xy[0] - w / 2 if anchor[0] == "m" else xy[0]
        for c in txt:
            d.text((x, xy[1]), c, font=font, fill=fill, anchor="l" + anchor[1])
            x += font.getlength(c) + spacing
    else:
        d.text(xy, txt, font=font, fill=fill, anchor=anchor)

def estrela(d, cx, cy, r, fill):
    import math
    pts = []
    for i in range(10):
        ang = math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.42
        pts.append((cx + rr * math.cos(ang), cy - rr * math.sin(ang)))
    d.polygon(pts, fill=fill)

def build():
    W, H = CFG["W"], CFG["H"]

    # fundo: gradiente vertical #2c5282 -> #4a90e2
    grad = Image.new("RGB", (1, H))
    gd = ImageDraw.Draw(grad)
    for y in range(H):
        t = (y / H) ** 0.85
        gd.point((0, y), fill=tuple(int(a + (b - a) * t) for a, b in zip(AZUL_ESC, AZUL)))
    img = grad.resize((W, H))

    # estrelas discretas de fundo (eco do logo)
    stars = Image.new("L", (W, H), 0)
    sd = ImageDraw.Draw(stars)
    for (x, y, r) in [(90, 235, 26), (985, 175, 20), (52, 560, 15), (1010, 640, 24),
                      (44, 830, 18), (1025, 795, 14), (60, 1700, 20), (1000, 1745, 26),
                      (150, 1855, 14), (905, 1880, 17)]:
        estrela(sd, x, y, r, 38)
    img.paste(Image.new("RGB", (W, H), BRANCO), (0, 0), stars)

    d = ImageDraw.Draw(img)

    # ---------------- selo branco com o logo ----------------
    SELO_R, SELO_CY = 174, 300
    d.ellipse([W // 2 - SELO_R, SELO_CY - SELO_R, W // 2 + SELO_R, SELO_CY + SELO_R], fill=BRANCO)
    logo = Image.open(caminho(CFG["logo"])).convert("L")
    logo = logo.resize((logo.width * 4, logo.height * 4), Image.LANCZOS)
    logo = logo.filter(ImageFilter.UnsharpMask(radius=3, percent=180, threshold=2))
    logo = logo.resize((272, 272), Image.LANCZOS)
    mask = logo.point(lambda v: 255 - v)                 # tinta = onde era escuro
    tinta = Image.new("RGB", logo.size, AZUL_ESC)
    img.paste(tinta, (W // 2 - 136, SELO_CY - 136), mask)

    # ---------------- identidade ----------------
    f_obra = F_cabe("Poppins-Bold.ttf", 44, CFG["nome_obra"], W - 140, spacing=4)
    texto(d, (W // 2, 545), CFG["nome_obra"], f_obra, BRANCO, spacing=4)
    f_lema = F_cabe("Lora-Italic-Variable.ttf", 33, CFG["lema"], W - 140)
    texto(d, (W // 2, 605), CFG["lema"], f_lema, (219, 234, 250))
    d.rounded_rectangle([W // 2 - 60, 655, W // 2 + 60, 659], radius=2, fill=BRANCO)

    # ---------------- chamada ----------------
    texto(d, (W // 2, 720), CFG["chamada"], F("Poppins-Medium.ttf", 38), (219, 234, 250), spacing=3)
    texto(d, (W // 2, 800), CFG["valor_texto"], F("Poppins-Bold.ttf", 96), BRANCO)

    # ---------------- cartao branco do Pix ----------------
    CX0, CY0, CX1, CY1 = 80, 880, W - 80, 1620
    d.rounded_rectangle([CX0 + 6, CY0 + 10, CX1 + 6, CY1 + 10], radius=52, fill=(35, 68, 112))
    d.rounded_rectangle([CX0, CY0, CX1, CY1], radius=52, fill=BRANCO)

    texto(d, (W // 2, 934), "PAGUE COM PIX", F("Poppins-Bold.ttf", 34), AZUL, spacing=5)

    payload = brcode(CFG["chave_pix"], CFG["nome_recebedor"], CFG["cidade"],
                     CFG["valor"], CFG["descricao"])
    qr = segno.make(payload, error="m")
    mods = qr.symbol_size(scale=1, border=2)[0]     # modulos + borda
    escala = max(1, round(430 / mods))              # escala inteira: modulos nitidos
    qr_temp = caminho("_qr_temp.png")
    qr.save(qr_temp, scale=escala, border=2, dark="#2c5282", light="white")
    qim = Image.open(qr_temp).convert("RGB")
    img.paste(qim, (W // 2 - qim.width // 2, 972 + (430 - qim.height) // 2))
    os.remove(qr_temp)

    d.rounded_rectangle([W // 2 - 200, 1420, W // 2 + 200, 1422], radius=1, fill=(226, 234, 244))
    texto(d, (W // 2, 1462), "CHAVE PIX (CELULAR)", F("Poppins-Medium.ttf", 27), AZUL, spacing=3)
    f_chave = F_cabe("Poppins-Bold.ttf", 62, CFG["chave_exibida"], CX1 - CX0 - 100)
    texto(d, (W // 2, 1516), CFG["chave_exibida"], f_chave, AZUL_ESC)
    f_rec = F_cabe("Poppins-Medium.ttf", 28, CFG["nome_recebedor"], CX1 - CX0 - 100)
    texto(d, (W // 2, 1572), CFG["nome_recebedor"], f_rec, (130, 146, 166))

    texto(d, (W // 2, 1678), CFG["sub"], F_cabe("Poppins-Regular.ttf", 32, CFG["sub"], W - 120),
          (223, 236, 250))

    # ---------------- rodape ----------------
    texto(d, (W // 2, 1768), CFG["rodape"], F("Poppins-Medium.ttf", 36), BRANCO)
    texto(d, (W // 2, 1836), CFG["bencao"], F("Lora-Italic-Variable.ttf", 38), (219, 234, 250))

    destino = caminho(CFG["out"])
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    img.save(destino, quality=95)
    print("PNG:", destino)
    print("Pix copia e cola:\n" + payload)
    return payload

if __name__ == "__main__":
    build()