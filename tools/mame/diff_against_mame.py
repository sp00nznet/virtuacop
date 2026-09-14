#!/usr/bin/env python3
"""
Compare this recompilation's rendering against MAME's, frame for frame.

Both sides dump, at intervals, a picture and the display list that produced
it. This lines the two runs up on the list and then diffs the pictures, so a
rendering difference is reported against a reference instead of against
somebody's memory of the arcade.

Lining them up is the fiddly part and cannot be done on frame number: our
field counter is not the game's frame counter, because the field boundary sits
inside the guest's busy-wait on the video status register, which it polls a
varying number of times per frame. So the same field number lands on a
different game frame from one run to the next. Match on the active display
list instead - the stream from the geometry read address, which the CPU has
been shown to compute identically.

Capture MAME's side with tools/mame/dump_display_list.lua, and ours with
MODEL2_SHOT_EVERY. Then:

    python tools/mame/diff_against_mame.py <mame_dir> <our_prefix> [out_dir]

<mame_dir> holds mame_<frame>.lst plus a snap/ directory of PNGs in frame
order; <our_prefix> is the MODEL2_SCREENSHOT prefix, so it finds
<prefix>.<field>.ppm and <prefix>.<field>.lst.

Prints, for each matched pair, how many pixels differ and where the worst
region is, and writes a side-by-side plus a difference mask for the pairs that
differ most.
"""
import glob
import os
import struct
import sys

try:
    from PIL import Image
    import numpy as np
except ImportError:
    raise SystemExit('needs Pillow and numpy')


def load_list(path):
    """(read address, tuple of dwords) for one captured display list."""
    data = open(path, 'rb').read()
    n = len(data) // 4
    words = struct.unpack('<%dI' % n, data[:n * 4])
    return words[0], words[1:]


def list_distance(a, b):
    """Dwords differing between two lists, over the shorter of the two."""
    wa, wb = a[1], b[1]
    n = min(len(wa), len(wb))
    if n == 0:
        return 1 << 30
    return sum(1 for i in range(n) if wa[i] != wb[i])


def as_rgb(path):
    im = Image.open(path).convert('RGB')
    return np.array(im), im


def crop_to_common(a, b):
    """MAME renders 512 wide including the horizontal blanking either side of
    our 496; centre them on each other rather than assuming an offset."""
    h = min(a.shape[0], b.shape[0])
    w = min(a.shape[1], b.shape[1])
    ax = (a.shape[1] - w) // 2
    bx = (b.shape[1] - w) // 2
    return a[:h, ax:ax + w], b[:h, bx:bx + w]


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    mame_dir, our_prefix = sys.argv[1], sys.argv[2]
    out_dir = sys.argv[3] if len(sys.argv) > 3 else 'mamediff'
    os.makedirs(out_dir, exist_ok=True)

    mame_lists = {}
    for p in sorted(glob.glob(os.path.join(mame_dir, 'mame_*.lst'))):
        frame = int(os.path.basename(p).split('_')[1].split('.')[0])
        mame_lists[frame] = load_list(p)

    snaps = sorted(glob.glob(os.path.join(mame_dir, 'msnap', '**', '*.png'),
                             recursive=True))
    frames_in_order = sorted(mame_lists)
    mame_png = dict(zip(frames_in_order, snaps))

    ours = {}
    for p in sorted(glob.glob(our_prefix + '.*.lst')):
        field = int(os.path.basename(p).split('.')[-2])
        ppm = p[:-4] + '.ppm'
        if os.path.exists(ppm):
            ours[field] = (load_list(p), ppm)

    if not mame_lists or not ours:
        raise SystemExit('nothing to compare (mame=%d ours=%d)'
                         % (len(mame_lists), len(ours)))

    print('%-8s %-10s %-8s %s' % ('field', 'mame frame', 'list', 'pixels differing'))
    worst = []
    for field in sorted(ours):
        (our_list, ppm) = ours[field]
        best_frame, best_dist = None, None
        for frame, ml in mame_lists.items():
            d = list_distance(our_list, ml)
            if best_dist is None or d < best_dist:
                best_frame, best_dist = frame, d

        if best_frame not in mame_png:
            continue
        a, _ = as_rgb(mame_png[best_frame])
        b, _ = as_rgb(ppm)
        a, b = crop_to_common(a, b)
        diff = (a.astype(int) - b.astype(int))
        bad = (np.abs(diff).sum(axis=2) > 24)
        pct = 100.0 * bad.sum() / bad.size
        print('%-8d %-10d %-8d %d (%.1f%%)'
              % (field, best_frame, best_dist, bad.sum(), pct))
        worst.append((bad.sum(), field, best_frame, a, b, bad))

    worst.sort(reverse=True)
    for rank, (n, field, frame, a, b, bad) in enumerate(worst[:3]):
        h, w, _ = a.shape
        canvas = np.zeros((h, w * 3, 3), dtype=np.uint8)
        canvas[:, :w] = a
        canvas[:, w:2 * w] = b
        canvas[:, 2 * w:][bad] = (255, 0, 0)
        name = os.path.join(out_dir, 'diff_%02d_f%05d_m%05d.png'
                            % (rank, field, frame))
        Image.fromarray(canvas).save(name)
        print('wrote', name, '(mame | ours | difference)')


if __name__ == '__main__':
    main()
