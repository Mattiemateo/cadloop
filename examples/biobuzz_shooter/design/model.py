"""Compact prototype; acceptance does not certify fabricated rotating parts."""
from cadloop.authoring import Scene
from fabricated import *
from standard_parts import (bearing_carrier_608, bearing_retainer_608,
                            bearing608_reference, flanged_hex_sleeve_608)


def build(p):
    scene = Scene()
    angle, motor_x = p['hood_angle_deg'], p['motor_center_mm']
    cx, cz = motor_position(motor_x)
    scene.add('base_plywood', base_panel())
    scene.add('turret_adapter', turret_adapter())
    scene.add('hood', hood(angle), parameters=('hood_angle_deg',))
    scene.add('feed_chute', feed_chute())
    for sign, side in ((-1, 'left'), (1, 'right')):
        scene.add(side + '_plywood', side_panel(sign, angle, motor_x), parameters=('hood_angle_deg', 'motor_center_mm'))
        origin = (0, sign * 44, 140)
        def placed(shape, offset=0):
            return along_y(shape.translate((0, 0, offset)), origin, positive=sign > 0)
        scene.add(side + '_carrier', placed(bearing_carrier_608()))
        scene.add(side + '_retainer', placed(bearing_retainer_608(), 10.15))
        scene.add(side + '_608_reference', placed(bearing608_reference(), 3.05))
        scene.add(side + '_sleeve', placed(flanged_hex_sleeve_608(), 3.15))
        for x, end in ((-112, 'rear'), (118, 'front')):
            scene.add(side + '_' + end + '_foot', base_corner(x, sign))
    scene.add('flywheel_core', along_y(flywheel_core(), (0, 0, 140)))
    scene.add('silicone_tire', along_y(flywheel_tire(), (0, 0, 140)))
    scene.add('main_shaft_reference', along_y(hex_shaft(140), (0, -57, 140)))
    scene.add('motor_mount', motor_mount(motor_x), parameters=('motor_center_mm',))
    scene.add('motor_reference', motor_reference(motor_x), parameters=('motor_center_mm',))
    scene.add('driver_shaft_reference', along_y(hex_shaft(45), (cx, 38, cz)))
    scene.add('wheel_sprocket_reference', sprocket_reference(0))
    scene.add('motor_sprocket_reference', sprocket_reference(cx, cz), parameters=('motor_center_mm',))
    scene.add('chain_guard', chain_guard())
    scene.add('camera_mount', camera_mount())
    scene.add('limelight_reference', limelight_reference())
    return scene
