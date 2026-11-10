#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gera a vinheta de ABERTURA (1080x1920): retrato do frei em moldura de arco,
na mesma identidade da vinheta de encerramento.
Gera tambem o lower third (tarja com o nome) em PNG transparente.
Rode: python vinheta_abertura.py
"""
import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

BASE = os.path.dirname(os.path.abspath(__file__))

def caminho(p):
    return p if os.path.isabs(p) else os.path.join(BASE, p)

# ----------------------------- CONFIG ---------------------------------------
CFG = dict(
    nome_obra = "Mission\u00e1rios De N. Sra. e S\u00e3o Bruno",
    nome      = "FREI VALDIR",
    papel     = "Casa de miss\u00e3o em Santa Teresa \u00b7 Rio de Janeiro",
    lema      = "\u201cVivemos pobres, com os pobres e para os pobres\u201d",
    rodape    = "@ifmdenossasenhora",

    retrato   = "uploads/frei_recorte.png",  # PNG do frame ja endireitado
    logo      = "uploads/0.png",
    out       = "outputs/vinheta_abertura_1080x1920.png",
    out_tarja = "outputs/lower_third_frei.png",
    W = 1080, H = 1920,
)

AZUL_ESC = (44, 82, 130)     # #2c5282
AZUL     = (74, 144, 226)    # #4a90e2
BRANCO   = (255, 255, 255)

# ------------------------------ FONTES --------------------------------------
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
    _cache_fontes[nome] = None
    return None

def F(name, size):
    c = _arquivo_da_fonte(name)
    return ImageFont.load_default() if c is None else ImageFont.truetype(c, size)

def F_cabe(name, size, txt, largura_max, spacing=0, size_min=18):
    while size > size_min:
        f = F(name, size)
        w = sum(f.getlength(ch) + spacing for ch in txt) - spacing if spacing else f.getlength(txt)
        if w <= largura_max:
            return f
        size -= 1
    return F(name, size_min)

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

def mascara_arco(w, h, ss=4):
    """Mascara de arco pleno: retangulo com topo em semicirculo."""
    m = Image.new("L", (w * ss, h * ss), 0)
    md = ImageDraw.Draw(m)
    r = w * ss // 2
    md.ellipse([0, 0, w * ss, w * ss], fill=255)          # topo redondo
    md.rectangle([0, r, w * ss, h * ss], fill=255)         # corpo
    return m.resize((w, h), Image.LANCZOS)

def fundo(W, H):
    grad = Image.new("RGB", (1, H))
    gd = ImageDraw.Draw(grad)
    for y in range(H):
        t = (y / H) ** 0.85
        gd.point((0, y), fill=tuple(int(a + (b - a) * t) for a, b in zip(AZUL_ESC, AZUL)))
    img = grad.resize((W, H))
    stars = Image.new("L", (W, H), 0)
    sd = ImageDraw.Draw(stars)
    for (x, y, r) in [(90, 300, 26), (985, 240, 20), (52, 620, 15), (1010, 700, 24),
                      (44, 980, 18), (1025, 900, 14), (70, 1520, 20), (1000, 1600, 26),
                      (150, 1810, 14), (905, 1855, 17)]:
        estrela(sd, x, y, r, 38)
    img.paste(Image.new("RGB", (W, H), BRANCO), (0, 0), stars)
    return img

# ------------------------------ abertura ------------------------------------
def build():
    W, H = CFG["W"], CFG["H"]
    img = fundo(W, H)
    d = ImageDraw.Draw(img)

    # ---------------- selo com o logo ----------------
    SELO_R, SELO_CY = 104, 210
    d.ellipse([W // 2 - SELO_R, SELO_CY - SELO_R, W // 2 + SELO_R, SELO_CY + SELO_R], fill=BRANCO)
    logo = Image.open(caminho(CFG["logo"])).convert("L")
    logo = logo.resize((logo.width * 4, logo.height * 4), Image.LANCZOS)
    logo = logo.filter(ImageFilter.UnsharpMask(radius=3, percent=180, threshold=2))
    logo = logo.resize((162, 162), Image.LANCZOS)
    img.paste(Image.new("RGB", logo.size, AZUL_ESC),
              (W // 2 - 81, SELO_CY - 81), logo.point(lambda v: 255 - v))

    texto(d, (W // 2, 372), CFG["nome_obra"],
          F_cabe("Poppins-Bold.ttf", 34, CFG["nome_obra"], W - 160, spacing=3), BRANCO, spacing=3)

    # ---------------- retrato em moldura de arco ----------------
    AW, AH, AX, AY = 620, 900, (W - 620) // 2, 450
    BORDA = 14

    ret = Image.open(caminho(CFG["retrato"])).convert("RGB")
    # cobre o arco preservando proporcao (equivalente a object-fit: cover)
    escala = max(AW / ret.width, AH / ret.height)
    ret = ret.resize((round(ret.width * escala), round(ret.height * escala)), Image.LANCZOS)
    ret = ret.crop(((ret.width - AW) // 2, 0, (ret.width - AW) // 2 + AW, AH))

    arco = mascara_arco(AW, AH)

    # moldura branca (arco um pouco maior) + sombra
    mold = mascara_arco(AW + BORDA * 2, AH + BORDA * 2)
    sombra = Image.new("RGB", (W, H))
    sombra_m = Image.new("L", (W, H), 0)
    sombra_m.paste(mold, (AX - BORDA + 8, AY - BORDA + 14))
    sombra_m = sombra_m.filter(ImageFilter.GaussianBlur(18))
    img.paste(Image.new("RGB", (W, H), (30, 60, 100)), (0, 0),
              sombra_m.point(lambda v: int(v * 0.55)))
    img.paste(Image.new("RGB", mold.size, BRANCO), (AX - BORDA, AY - BORDA), mold)
    img.paste(ret, (AX, AY), arco)

    # ---------------- identificacao ----------------
    d = ImageDraw.Draw(img)
    texto(d, (W // 2, 1452), CFG["nome"], F_cabe("Poppins-Bold.ttf", 78, CFG["nome"], W - 160, spacing=4),
          BRANCO, spacing=4)
    texto(d, (W // 2, 1522), CFG["papel"],
          F_cabe("Poppins-Regular.ttf", 32, CFG["papel"], W - 160), (214, 232, 250))
    d.rounded_rectangle([W // 2 - 60, 1580, W // 2 + 60, 1584], radius=2, fill=BRANCO)
    texto(d, (W // 2, 1650), CFG["lema"],
          F_cabe("Lora-Italic-Variable.ttf", 36, CFG["lema"], W - 140), (226, 240, 252))

    texto(d, (W // 2, 1790), CFG["rodape"], F("Poppins-Medium.ttf", 34), (206, 228, 250))

    destino = caminho(CFG["out"])
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    img.save(destino, quality=95)
    print("PNG abertura:", destino)
    return destino

# ---------------------------- lower third -----------------------------------
def build_tarja():
    """Tarja transparente 1080x1920 para sobrepor ao video (fica no rodape)."""
    W, H = CFG["W"], CFG["H"]
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    X0, Y0 = 70, 740   # acima da faixa das legendas queimadas
    f_nome = F("Poppins-Bold.ttf", 56)
    f_sub = F_cabe("Poppins-Regular.ttf", 28, CFG["papel"], 700)
    larg = max(f_nome.getlength(CFG["nome"]) + 4 * len(CFG["nome"]), f_sub.getlength(CFG["papel"]))
    X1, Y1 = X0 + larg + 120, Y0 + 150

    d.rounded_rectangle([X0, Y0, X1, Y1], radius=20, fill=AZUL_ESC + (235,))
    d.rounded_rectangle([X0, Y0, X0 + 10, Y1], radius=5, fill=AZUL + (255,))
    texto(d, (X0 + 44, Y0 + 52), CFG["nome"], f_nome, BRANCO + (255,), anchor="lm", spacing=4)
    texto(d, (X0 + 46, Y0 + 105), CFG["papel"], f_sub, (200, 224, 248, 255), anchor="lm")

    destino = caminho(CFG["out_tarja"])
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    img.save(destino)
    print("PNG tarja:  ", destino)
    return destino

if __name__ == "__main__":
    build()
    build_tarja()