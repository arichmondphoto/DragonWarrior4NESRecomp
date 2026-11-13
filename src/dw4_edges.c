/*
 * dw4_edges.c - Dragon Warrior IV's map edges at the full 256x240 picture.
 *
 * The NES nametable holds exactly 240 lines, so on a vertically scrolling map
 * the row leaving the screen at one edge is the same memory row the game
 * fills for the other edge. The game writes the incoming row about 10 frames
 * after it starts scrolling into view, and its colours (attribute bytes) 4
 * frames after that: on a TV the overscan hid it, at the full 256x240 it
 * flickers. The left 8 pixels are masked by the game for the same reason.
 *
 * The edges are drawn from the map instead:
 *
 *  - Towns, castles, shrines, dungeons: the game keeps the whole map in WRAM
 *    ($7800 cells, W x H = $3F x $40, hero cell $44/$45, border cell $0520;
 *    $7600 the 32 metatiles' four tile numbers, $76C0 their sub-palettes).
 *  - Overworld-style maps ($28 = 0: the main world 256x256, Gottside 64x64,
 *    the Underworld 62x54; hero cell $42/$43): decoded at start from the ROM
 *    (bank $0B, row pointers $A590 / $AB65 / $AE89: 2-byte pointer + two
 *    sizes; bytes are runs, tile = b >> 5, length = (b & 31) + 1, and
 *    b >= $E8 is one tile b - $E0; Data Crystal's DW4 ROM map). Sea (tile 0)
 *    is drawn with one of 16 shoreline metatiles at $7680, picked by which
 *    of its N/E/S/W neighbours (1/2/4/8) are not sea.
 *
 *  - Each frame the nametable is matched against the map around the hero to
 *    find where map cell (0,0) sits in the nametable ring (64 x 30 tiles; it
 *    changes with every map load) and, on the overworld, which world it is.
 *    No match (battles, full-screen menus, the title) = no repair.
 *  - What a map value looks like is learned from the correctly drawn middle
 *    of the screen: the upper bits of a town cell mark rooms and roofs the
 *    game shows or hides, and at a given moment a value is drawn the same way
 *    everywhere (99.6% of the captured map views). Unseen values fall back to
 *    their plain metatile.
 *  - nesrecomp patch 0021's background hook replaces every tile fetched for
 *    the top/bottom 16 lines and left/right 16 pixels by the tile and palette
 *    its map cell should show, and the left 8 pixels are unmasked. Tiles that
 *    are not map tiles (windows, text) are left alone.
 *
 * Presentation only: the game's memories are never written. Developer
 * option: --no-edge-repair.
 */
#include "cyc_host_extras.h"
#include "cyc_core.h"
#include "cyc_mod.h"
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define EDGE_LINES 16       /* top and bottom lines repaired */
#define EDGE_PIXELS 16      /* left and right pixels repaired */
#define HERO_X 120          /* screen position of the hero's map cell (roughly) */
#define HERO_Y 112
#define SEA_KEYS 32         /* overworld look keys: tile, or SEA_KEYS + shore mask for sea */

typedef struct { uint8_t q[4], pal; int8_t conf; } Look;
#define LOOKS 4             /* looks remembered per map value (animations, rooms shown/hidden) */
typedef struct { const char *name; uint16_t table; int w, h; uint8_t *cells; } World;

static World worlds[] = {
    { "main", 0xA590, 256, 256, NULL },
    { "Gottside", 0xAB65, 64, 64, NULL },
    { "Underworld", 0xAE89, 62, 54, NULL },
};
#define NWORLDS (int)(sizeof worlds / sizeof worlds[0])

static struct {
    bool enabled, valid, overworld;
    int world;              /* overworld: index into worlds[] */
    int dx, dy;             /* nametable tile of map tile (0,0), mod 64 / 30 */
    int w, h, hx, hy;
    unsigned key;           /* what was learned belongs to this map */
    int search_wait;
    Look look[256][LOOKS];  /* per map value, most seen first after learn() */
    uint8_t map_tile[256];  /* tile numbers that belong to the map */
    const uint8_t *ram, *wram, *ciram;
} E = { .enabled = true };

/* ---- the overworlds, decoded from the ROM ---- */

static void decode_worlds(void)
{
    if (worlds[0].cells) return;
    size_t n = cyc_mod_copy_cart_payload(NULL, 0);
    if (n < 12 * 0x4000) return;
    uint8_t *rom = malloc(n);
    if (!rom) return;
    cyc_mod_copy_cart_payload(rom, n);
    const uint8_t *bank = rom + 0x0B * 0x4000;
#define RD(a) bank[(uint16_t)(a) - 0x8000]
    for (int i = 0; i < NWORLDS; i++) {
        World *wd = &worlds[i];
        uint8_t *c = calloc((size_t)wd->w * wd->h, 1);
        if (!c) break;
        for (int y = 0; y < wd->h; y++) {
            uint16_t p = (uint16_t)(wd->table + 4 * y), a = (uint16_t)(RD(p) | RD(p + 1) << 8);
            int size = RD(p + 3), x = 0;
            if (a < 0x8000 || a >= 0xC000) continue;
            for (int k = 0; k < size && x < wd->w && a + k < 0xC000; k++) {
                uint8_t b = RD(a + k);
                if (b >= 0xE8) c[y * wd->w + x++] = (uint8_t)(b - 0xE0);
                else for (int r = (b & 31) + 1; r > 0 && x < wd->w; r--) c[y * wd->w + x++] = (uint8_t)(b >> 5);
            }
        }
        wd->cells = c;
    }
#undef RD
    free(rom);
}

/* ---- nametable ---- */

static inline uint8_t nt_tile(int tx, int ty)
{
    tx &= 63;
    return E.ciram[(tx >> 5) * 0x400 + ty * 32 + (tx & 31)];
}

static inline uint8_t nt_pal(int tx, int ty)
{
    tx &= 63;
    uint8_t a = E.ciram[(tx >> 5) * 0x400 + 0x3C0 + (ty >> 2) * 8 + ((tx & 31) >> 2)];
    return (uint8_t)((a >> (((ty & 2) ? 4 : 0) + ((tx & 2) ? 2 : 0))) & 3);
}

static inline int mod(int a, int m) { a %= m; return a < 0 ? a + m : a; }
static inline int floordiv(int a, int b) { return a >= 0 ? a / b : -((-a + b - 1) / b); }

/* ---- what a map cell is ---- */

static inline int world_tile(const World *wd, int x, int y) { return wd->cells[mod(y, wd->h) * wd->w + mod(x, wd->w)]; }

/* The look key of map cell (x, y): a town cell's byte, or an overworld tile
 * (sea: SEA_KEYS + which neighbours are not sea). */
static int cell_key(int x, int y)
{
    if (E.overworld) {
        const World *wd = &worlds[E.world];
        int t = world_tile(wd, x, y);
        if (t) return t;
        return SEA_KEYS | (world_tile(wd, x, y - 1) != 0) | (world_tile(wd, x + 1, y) != 0) << 1 |
               (world_tile(wd, x, y + 1) != 0) << 2 | (world_tile(wd, x - 1, y) != 0) << 3;
    }
    if (x < 0 || y < 0 || x >= E.w || y >= E.h) return E.ram[0x520];   /* the map's border cell */
    return E.wram[0x1800 + y * E.w + x];
}

/* The plain metatile of a key (its four tile numbers), or NULL; *pal its palette. */
static const uint8_t *plain(int key, int *pal)
{
    if (E.overworld) {
        if (key >= SEA_KEYS) { *pal = E.wram[0x16C0] & 3; return E.wram + 0x1680 + (key - SEA_KEYS) * 4; }
        *pal = E.wram[0x16C0 + key] & 3; return E.wram + 0x1600 + key * 4;
    }
    if (key >> 5) return NULL;                              /* rooms and roofs: only as learned */
    *pal = E.wram[0x16C0 + key] & 3;
    return E.wram + 0x1600 + key * 4;
}

/* How many cells around the hero the nametable shows as their plain
 * metatile, with map tile (0,0) at nametable tile (dx, dy). */
static int score(int dx, int dy, int *total)
{
    int n = 0, t = 0, pal;
    for (int y = E.hy - 5; y <= E.hy + 5; y++)
        for (int x = E.hx - 6; x <= E.hx + 6; x++) {
            if (!E.overworld && (x < 0 || y < 0 || x >= E.w || y >= E.h)) continue;
            const uint8_t *d = plain(cell_key(x, y), &pal);
            /* only cells that say something: a metatile of four equal tiles
               (blank, flat colour) matches any blank screen */
            if (!d || (d[0] == d[1] && d[1] == d[2] && d[2] == d[3])) continue;
            int tx = 2 * x + dx, ty = mod(2 * y + dy, 30);
            uint8_t a = nt_tile(tx, ty), b = nt_tile(tx + 1, ty), c = nt_tile(tx, ty + 1), e = nt_tile(tx + 1, ty + 1);
            /* a window or text over the cell says nothing about the map */
            if (!E.map_tile[a] || !E.map_tile[b] || !E.map_tile[c] || !E.map_tile[e]) continue;
            t++;
            n += a == d[0] && b == d[1] && c == d[2] && e == d[3];
        }
    *total = t;
    return n;
}

/* The best ring offset; true if it explains at least 60% of the cells. */
static bool search(void)
{
    int best = -1, bdx = 0, bdy = 0, total = 0;
    for (int dy = 0; dy < 30; dy += 2)
        for (int dx = 0; dx < 64; dx += 2) {
            int v = score(dx, dy, &total);
            if (v > best) { best = v; bdx = dx; bdy = dy; }
        }
    if (getenv("DW4_EDGES_DEBUG") && getenv("DW4_EDGES_DEBUG")[0] == '2')
        fprintf(stderr, "dw4_edges: search %s best %d of %d at %d,%d hero %d,%d\n",
                E.overworld ? worlds[E.world].name : "town", best, total, bdx, bdy, E.hx, E.hy);
    if (total < 24 || 5 * best < 3 * total) return false;
    E.dx = bdx; E.dy = bdy;
    return true;
}

/* The tile numbers maps are made of: the metatiles (+ shorelines) and what
 * was learned. Anything else on screen is a window or text. */
static void map_tiles(void)
{
    memset(E.map_tile, 0, sizeof E.map_tile);
    for (int i = 0; i < 32 * 4; i++) E.map_tile[E.wram[0x1600 + i]] = 1;
    if (E.overworld) for (int i = 0; i < 16 * 4; i++) E.map_tile[E.wram[0x1680 + i]] = 1;
    for (int i = 0; i < 256; i++)
        for (int j = 0; j < LOOKS; j++)
            if (E.look[i][j].conf > 0)
                for (int k = 0; k < 4; k++) E.map_tile[E.look[i][j].q[k]] = 1;
}

static void learn(void)
{
    /* the middle of the screen, where the game has drawn everything right */
    for (int y = E.hy - 5; y <= E.hy + 5; y++)
        for (int x = E.hx - 6; x <= E.hx + 6; x++) {
            int c = cell_key(x, y), tx = 2 * x + E.dx, ty = mod(2 * y + E.dy, 30);
            uint8_t q[4] = { nt_tile(tx, ty), nt_tile(tx + 1, ty), nt_tile(tx, ty + 1), nt_tile(tx + 1, ty + 1) };
            if (!E.map_tile[q[0]] || !E.map_tile[q[1]] || !E.map_tile[q[2]] || !E.map_tile[q[3]]) continue;  /* a window */
            uint8_t pal = nt_pal(tx, ty);
            Look *l = E.look[c];
            /* every look a value shows (animation frames, rooms shown and
               hidden), counted; the least seen one makes room for a new one */
            int j = 0;
            while (j < LOOKS && !(l[j].conf > 0 && !memcmp(l[j].q, q, 4) && l[j].pal == pal)) j++;
            if (j < LOOKS) { if (l[j].conf < 100) l[j].conf++; }
            else {
                j = LOOKS - 1;
                memcpy(l[j].q, q, 4); l[j].pal = pal; l[j].conf = 1;
            }
            while (j > 0 && l[j].conf > l[j - 1].conf) { Look t = l[j]; l[j] = l[j - 1]; l[j - 1] = t; j--; }
        }
    map_tiles();
}

static void frame_begin(void *ctx)
{
    (void)ctx;
    size_t n;
    E.ram = cyc_cpu_ram();
    E.wram = cyc_cart_ram(&n);
    E.ciram = cyc_ppu_ciram(&n);
    bool was = E.valid;
    E.valid = false;
    if (!E.enabled || !E.ram || !E.wram || !E.ciram || n < 0x800) goto done;
    bool ow = E.ram[0x28] == 0;
    unsigned key;
    if (ow) {
        if (!worlds[0].cells) goto done;
        E.hx = E.ram[0x42]; E.hy = E.ram[0x43];
        key = 0xFF000000u | (unsigned)E.ram[0x63] << 8 | E.ram[0x64];
    } else {
        E.w = E.ram[0x3F]; E.h = E.ram[0x40]; E.hx = E.ram[0x44]; E.hy = E.ram[0x45];
        if (E.w < 4 || E.h < 4 || E.w * E.h > 0x800) goto done;
        key = (unsigned)E.ram[0x63] << 24 | (unsigned)E.ram[0x64] << 16 | (unsigned)E.w << 8 | (unsigned)E.h;
    }
    if (ow != E.overworld || key != E.key) {
        E.overworld = ow; E.key = key;
        memset(E.look, 0, sizeof E.look); E.search_wait = 0; was = false;
    }
    map_tiles();
    int total, s = was ? score(E.dx, E.dy, &total) : 0;
    if (was && total >= 24 && 2 * s >= total) E.valid = true;
    else if (was && total < 24) E.valid = true;            /* mostly covered by windows: keep what we had */
    else if (E.search_wait > 0 && !was) E.search_wait--;
    else {
        /* (re-based: the overworld moves its ring as the hero walks) */
        if (ow) {
            /* which world: the current one first */
            int first = E.world;
            for (int i = 0; i < NWORLDS && !E.valid; i++) {
                int wi = (first + i) % NWORLDS;
                if (!worlds[wi].cells) continue;
                E.world = wi;
                E.valid = search();
            }
        } else E.valid = search();
        if (E.valid) memset(E.look, 0, sizeof E.look);
        else E.search_wait = 8;
    }
    if (E.valid) learn();
    if (E.valid != was && getenv("DW4_EDGES_DEBUG"))
        fprintf(stderr, "dw4_edges: %s %s offset %d,%d hero %d,%d\n", E.valid ? "on" : "off",
                E.overworld ? worlds[E.world].name : "town/dungeon", E.dx, E.dy, E.hx, E.hy);
done:
    cyc_ppu_set_show_left(E.valid);
}

static int bg_hook(void *ctx, int line, int x, uint16_t v, uint8_t tile)
{
    (void)ctx;
    if (!E.valid) return -1;
    if (line >= EDGE_LINES && line < 240 - EDGE_LINES && x >= EDGE_PIXELS && x < 256 - EDGE_PIXELS) return -1;
    if (!E.map_tile[tile]) return -1;                       /* a window or text */
    int tx = (v & 31) + ((v >> 10) & 1) * 32, ty = (v >> 5) & 31;
    if (ty >= 30) return -1;
    /* the map tile column/row this nametable tile stands for, nearest to the hero */
    int wx = mod(tx - E.dx, 64), wy = mod(ty - E.dy, 30);
    int ex = 2 * E.hx + floordiv(x - HERO_X, 8), ey = 2 * E.hy + floordiv(line - HERO_Y, 8);
    wx += 64 * floordiv(ex - wx + 32, 64);
    wy += 30 * floordiv(ey - wy + 15, 30);
    int c = cell_key(floordiv(wx, 2), floordiv(wy, 2)), q = (wx & 1) | (wy & 1) << 1, pal;
    const Look *l = E.look[c];
    /* the game's own drawing of this cell, if it is one of the cell's looks
       (an animation frame, a room's current state): keep it, with that
       look's colours (the attribute byte may not be written yet) */
    int cx = tx & ~1, cy = ty & ~1;
    uint8_t now[4] = { nt_tile(cx, cy), nt_tile(cx + 1, cy), nt_tile(cx, cy + 1), nt_tile(cx + 1, cy + 1) };
    for (int j = 0; j < LOOKS; j++)
        if (l[j].conf > 0 && !memcmp(l[j].q, now, 4)) return l[j].q[q] | l[j].pal << 8;
    const uint8_t *d = plain(c, &pal);
    if (d && !memcmp(d, now, 4)) return d[q] | pal << 8;
    if (l[0].conf > 0) return l[0].q[q] | l[0].pal << 8;   /* the look seen most */
    return d ? d[q] | pal << 8 : -1;
}

static void power_on(void *ctx)
{
    (void)ctx;
    decode_worlds();
    memset(E.look, 0, sizeof E.look);
    E.valid = false; E.key = 0; E.search_wait = 0;
    cyc_ppu_set_bg_tile_hook(E.enabled ? bg_hook : NULL, NULL);
    cyc_ppu_set_show_left(false);
}

static void state_loaded(void *ctx) { power_on(ctx); }

static const CycHostOption options[] = {
    { "--no-edge-repair", false, "draw the map's edge rows as the game left them (as on a TV without overscan)" },
};

static bool option(void *ctx, const char *name, const char *value)
{
    (void)ctx; (void)value;
    if (!strcmp(name, "--no-edge-repair")) { E.enabled = false; cyc_ppu_set_bg_tile_hook(NULL, NULL); return true; }
    return false;
}

static const CycHostExtras extras = {
    .power_on = power_on,
    .frame_begin = frame_begin,
    .options = options,
    .option_count = sizeof options / sizeof options[0],
    .option = option,
    .state_loaded = state_loaded,
};

const CycHostExtras *cyc_host_extras(void) { return &extras; }
