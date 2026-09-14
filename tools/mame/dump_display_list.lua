-- Capture Virtua Cop's active display list and a matching snapshot, so a run
-- here can be lined up against a run of the recompilation.
--
-- Writes <VCOP_DUMP_DIR>/mame_<frame>.lst: the geometry read address followed
-- by 8192 dwords of the list it points at. Most of buffer RAM is never
-- touched, so hashing the whole 128KB matches every frame against every
-- other; the active list is what identifies a moment in the game.
--
-- VCOP_FRAMES picks the frames, as "first:last:step" (default 560:900:20).
--
-- Use emu.register_frame. add_machine_frame_notifier is the non-deprecated
-- spelling and did not fire here.

local outdir = os.getenv("VCOP_DUMP_DIR") or "."
local spec   = os.getenv("VCOP_FRAMES") or "560:900:20"
local first, last, step = spec:match("(%d+):(%d+):(%d+)")
first, last, step = tonumber(first), tonumber(last), tonumber(step)

local frame = 0
local mem = nil

emu.register_frame(function()
    frame = frame + 1
    if not mem then
        local cpu = manager.machine.devices[":maincpu"]
        if cpu then mem = cpu.spaces["program"] end
    end
    if not mem then return end
    if frame < first or frame > last or ((frame - first) % step) ~= 0 then
        return
    end

    -- 0x00803008 reads back the geometry engine's list read address.
    local start = mem:read_u32(0x00803008) & 0x1FFFF
    local fh = io.open(string.format("%s/mame_%05d.lst", outdir, frame), "wb")
    if not fh then return end

    local function put(v)
        fh:write(string.char(v & 0xFF, (v >> 8) & 0xFF,
                             (v >> 16) & 0xFF, (v >> 24) & 0xFF))
    end

    put(start)
    for i = 0, 8191 do
        put(mem:read_u32(0x00900000 + ((start + i * 4) & 0x1FFFC)))
    end
    -- Layer 0's name table too. On a screen with no 3D the display list sits
    -- idle and matches every other idle frame; the text on screen does not.
    for a = 0, 0x1FFC, 4 do
        put(mem:read_u32(0x01000000 + a))
    end
    fh:close()

    manager.machine.video:snapshot()
    print("PAIR " .. frame)
end)
