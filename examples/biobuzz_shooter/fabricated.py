"""Shooter parts in millimetres; +X shoots forward, +Z is up, shafts parallel Y.

Purchased-component solids are explicitly simplified reference envelopes.
Their dimensions are from the manufacturer drawings listed in SOURCES.md.
"""
import math
import cadquery as cq


def box(x, y, z, center):
    return cq.Workplane('XY').box(x, y, z).val().translate(center)


def cylinder(radius, length, origin=(0, 0, 0), direction=(0, 0, 1)):
    return cq.Solid.makeCylinder(radius, length, cq.Vector(*origin), cq.Vector(*direction))


def hex_shaft(length, af=5):
    return cq.Workplane('XY').polygon(6, 2 * af / math.sqrt(3)).extrude(length).val()


def along_y(shape, origin=(0, 0, 0), positive=True):
    return shape.rotate((0, 0, 0), (1, 0, 0), -90 if positive else 90).translate(origin)


def flywheel_core():
    """Cast-in core: 72 mm body, 80 mm keys/flanges, 44 mm central hub."""
    core = cylinder(36, 40, (0, 0, -20)).fuse(cylinder(9, 44, (0, 0, -22)))
    for z in (-17, 14):
        core = core.fuse(cylinder(40, 3, (0, 0, z)))
    for degrees in range(0, 360, 60):
        a = math.radians(degrees)
        core = core.fuse(cylinder(4, 24, (36 * math.cos(a), 36 * math.sin(a), -12)))
    return core.cut(hex_shaft(46, 5.1).translate((0, 0, -23))).clean()


def flywheel_tire():
    return (cylinder(50, 40, (0, 0, -20)).cut(flywheel_core())
            .cut(cylinder(9, 42, (0, 0, -21))).clean())


def motor_position(distance=76.2):
    return distance * math.cos(math.radians(60)), 140 + distance * math.sin(math.radians(60))


def drive_rotated(shape):
    return shape.rotate((0, 0, 140), (0, 1, 140), -60)


def hood_mounts(angle=65):
    radius = 50 + 71.12 - 3 + 8
    return [(radius * math.cos(math.radians(a)), 140 + radius * math.sin(math.radians(a)))
            for a in (-165, -110, angle - 95)]


def hood(angle=65):
    inner, outer = 118.12, 122.12
    start, end = -180, angle - 90
    def point(radius, a):
        a = math.radians(a)
        return radius * math.cos(a), 140 + radius * math.sin(a)
    shape = (cq.Workplane('XZ').moveTo(*point(inner, start))
             .threePointArc(point(inner, (start + end) / 2), point(inner, end))
             .lineTo(*point(outer, end))
             .threePointArc(point(outer, (start + end) / 2), point(outer, start))
             .close().extrude(41, both=True).val())
    for x, z in hood_mounts(angle):
        shape = shape.fuse(cylinder(6, 82, (x, -41, z), (0, 1, 0)))
        for sign in (-1, 1):
            shape = shape.cut(cylinder(1.7, 9, (x, sign * 41, z), (0, -sign, 0)))
            shape = shape.cut(box(5.6, 2.8, 5.6, (x, sign * 39.6, z)))
    return shape.clean()


def side_panel(sign, angle=65, motor_x=76.2):
    # Actual 3 mm plywood; parts sit on the base top at Z=9 mm.
    outline = [(-132, 9), (138, 9), (138, 190), (98, 264), (20, 264),
               (-25, 210), (-119, 210), (-132, 197)]
    part = cq.Workplane('XZ').polyline(outline).close().extrude(3).val()
    part = part.translate((0, 44 if sign > 0 else -41, 0))
    y = sign * 42.5
    holes = [(0, 140, 10)]
    holes += [(x, 140 + z, 1.7) for x in (-15, 15) for z in (-15, 15)]
    holes += [(x, z, 1.7) for x, z in hood_mounts(angle)[:2]]
    # Common side panels accept replacement hoods from 55 to 72 degrees.
    # The forward screw follows an actual arc slot, not a new hole per hood.
    inner, outer = 126.12 - 1.7, 126.12 + 1.7
    def arc_point(radius, degrees):
        a = math.radians(degrees)
        return radius * math.cos(a), 140 + radius * math.sin(a)
    slot = (cq.Workplane('XZ').moveTo(*arc_point(inner, -40))
            .threePointArc(arc_point(inner, -31.5), arc_point(inner, -23))
            .lineTo(*arc_point(outer, -23))
            .threePointArc(arc_point(outer, -31.5), arc_point(outer, -40))
            .close().extrude(4, both=True).val().translate((0, y, 0)))
    for degrees in (-40, -23):
        x, z = arc_point(126.12, degrees)
        slot = slot.fuse(cylinder(1.7, 8, (x, y - 4, z), (0, 1, 0)))
    part = part.cut(slot)
    holes += [(x, z, 1.7) for x in (-112, 118) for z in (17,)]
    holes += [(x, z, 1.7) for x in (-112, -52) for z in (184,)]
    for x, z, radius in holes:
        part = part.cut(cylinder(radius, 6, (x, y - 3, z), (0, 1, 0)))
    # The motor body passes through the left wall; the face mount bolts outside right.
    cx, cz = motor_position(76.2)
    motor_slot = box(6, 8, 45, (cx, y, cz)).fuse(
        cylinder(22.5, 8, (cx - 3, y - 4, cz), (0, 1, 0))).fuse(
        cylinder(22.5, 8, (cx + 3, y - 4, cz), (0, 1, 0)))
    part = part.cut(motor_slot)
    if sign > 0:
        for dx in (-27, 27):
            for dz in (-27, 27):
                x, z = cx + dx, cz + dz
                slot = box(6, 8, 3.4, (x, y, z))
                for sx in (-3, 3):
                    slot = slot.fuse(cylinder(1.7, 8, (x + sx, y - 4, z), (0, 1, 0)))
                part = part.cut(slot)
        for x in (-30, 114.2):
            for z in (113, 167):
                hole = cylinder(1.7, 8, (x, y - 4, z), (0, 1, 0))
                part = part.cut(drive_rotated(hole))
    return part.clean()


def base_panel():
    part = box(284, 96, 3, (8, 0, 7.5))
    for x in (-30, 30):
        for y in (-30, 30):
            part = part.cut(cylinder(1.7, 5, (x, y, 5)))
    for x in (-112, 118):
        for y in (-34, 34):
            part = part.cut(cylinder(1.7, 5, (x, y, 5)))
    for x in (136, 146):
        for y in (-32, 32):
            part = part.cut(cylinder(1.7, 5, (x, y, 5)))
    return part.clean()


def base_corner(x, sign):
    # Two orthogonal M3 fasteners; nut pockets are accessible before assembly.
    part = box(16, 16, 16, (x, sign * 33, 17))
    part = part.cut(cylinder(1.7, 18, (x, sign * 34, 8)))
    part = part.cut(box(5.6, 5.6, 2.8, (x, sign * 34, 23.6)))
    part = part.cut(cylinder(1.7, 18, (x, sign * 42, 17), (0, -sign, 0)))
    part = part.cut(box(5.6, 2.8, 5.6, (x, sign * 26.4, 17)))
    return part.clean()


def turret_adapter():
    part = box(88, 88, 6, (0, 0, 3))
    # Shooter-side 60 mm square; turret-side 76 mm square is replaceable/provisional.
    for pitch in (60, 76):
        for x in (-pitch / 2, pitch / 2):
            for y in (-pitch / 2, pitch / 2):
                part = part.cut(cylinder(1.7, 8, (x, y, -1)))
                part = part.cut(box(5.6, 5.6, 2.8, (x, y, 1.4 if pitch == 60 else 4.6)))
    return part.clean()


def motor_mount(motor_x=76.2):
    # Static gearbox case: six M3 on a 32 mm PCD, three alternating used.
    cx, cz = motor_position(motor_x)
    part = box(62, 6, 62, (cx, 47, cz))
    part = part.cut(cylinder(12, 8, (cx, 43, cz), (0, 1, 0)))
    for degrees in (90, 210, 330):
        a = math.radians(degrees)
        part = part.cut(cylinder(1.7, 8, (cx + 16 * math.cos(a), 43,
                                         cz + 16 * math.sin(a)), (0, 1, 0)))
    for dx in (-27, 27):
        for dz in (-27, 27):
            x, z = cx + dx, cz + dz
            part = part.cut(cylinder(1.7, 8, (x, 43, z), (0, 1, 0)))
            part = part.cut(box(5.6, 2.8, 5.6, (x, 48.6, z)))
    return part.clean()


def motor_reference(motor_x=76.2):
    # Conservative round enclosure at maximum case width; internal details omitted.
    cx, cz = motor_position(motor_x)
    part = cylinder(21.87, 90, (cx, -46, cz), (0, 1, 0))
    part = part.fuse(cylinder(10, 6, (cx, 44, cz), (0, 1, 0)))
    # Shaft socket envelope only: actual insertion must be checked on the gearbox.
    part = part.cut(along_y(hex_shaft(22, 5.1), (cx, 29, cz)))
    return part.clean()


def sprocket_reference(x, z=140):
    # REV-41-1338: axial envelope 15 mm, tooth-clearance diameter 24.1 mm.
    # Hub/teeth are simplified; the chain is specified separately, not simulated here.
    part = cylinder(12.05, 15)
    part = part.cut(hex_shaft(15, 5.1))
    return along_y(part, (x, 58.55, z))


def chain_guard():
    part = box(156.2, 28, 66, (42.1, 72, 140))
    part = part.cut(box(148.2, 27, 58, (42.1, 70.5, 140)))
    for x in (-30, 114.2):
        for z in (113, 167):
            part = part.fuse(cylinder(5, 40, (x, 44, z), (0, 1, 0)))
            part = part.cut(cylinder(1.7, 10, (x, 43, z), (0, 1, 0)))
            part = part.cut(box(5.6, 2.8, 5.6, (x, 45.4, z)))
    return drive_rotated(part.clean())


def camera_transform(shape):
    return shape.rotate((0, 0, 0), (0, 1, 0), -20).translate((145, 0, 48))


def limelight_reference():
    return camera_transform(box(16.8, 72.11, 48.11, (8.4, 0, 0)))


def camera_mount():
    plate = box(4, 80, 36, (-2, 0, 0))
    for y in (-32, 32):
        for z in (-4, 4):
            plate = plate.cut(cylinder(1.7, 6, (-5, y, z), (1, 0, 0)))
    part = camera_transform(plate)
    foot = box(24, 80, 6, (140, 0, 12))
    for x in (136, 146):
        for y in (-32, 32):
            foot = foot.cut(cylinder(1.7, 8, (x, y, 8)))
            foot = foot.cut(box(5.6, 5.6, 2.8, (x, y, 13.6)))
    # Two ribs stop below the mounting screws and the camera enclosure.
    for y in (-25, 25):
        rib = (cq.Workplane('XZ').polyline([(130, 15), (150, 15), (146, 42), (138, 29)])
               .close().extrude(3, both=True).val().translate((0, y, 0)))
        part = part.fuse(rib)
    return part.fuse(foot).clean()


def feed_chute():
    center = -82.56
    part = box(84, 82, 32, (center, 0, 194))
    part = part.cut(box(78, 76, 34, (center, 0, 194)))
    # Two M3 fixings on each side, square nuts inserted from the inner face.
    for x in (-112, -52):
        for sign in (-1, 1):
            part = part.fuse(box(10, 6, 12, (x, sign * 38, 184)))
            part = part.cut(cylinder(1.7, 8, (x, sign * 42, 184), (0, -sign, 0)))
            part = part.cut(box(5.6, 2.8, 5.6, (x, sign * 36.4, 184)))
    return part.clean()
