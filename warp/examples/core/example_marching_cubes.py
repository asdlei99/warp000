# Copyright (c) 2022 NVIDIA CORPORATION.  All rights reserved.
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto.  Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.

###########################################################################
# Example Marching Cubes
#
# Shows how use the built-in marching cubes functionality to extract
# the iso-surface from a density field.
#
# Note: requires a CUDA-capable device
###########################################################################


import os
from typing import Optional

import warp as wp
import warp.render

wp.init()


@wp.func
def sdf_create_box(pos: wp.vec3, size: wp.vec3):
    """Creates a SDF box primitive."""
    # https://iquilezles.org/articles/distfunctions
    q = wp.vec3(
        wp.abs(pos[0]) - size[0],
        wp.abs(pos[1]) - size[1],
        wp.abs(pos[2]) - size[2],
    )
    qp = wp.vec3(wp.max(q[0], 0.0), wp.max(q[1], 0.0), wp.max(q[2], 0.0))
    return wp.length(qp) + wp.min(wp.max(q[0], wp.max(q[1], q[2])), 0.0)


@wp.func
def sdf_create_torus(pos: wp.vec3, major_radius: float, minor_radius: float):
    """Creates a SDF torus primitive."""
    # https://iquilezles.org/articles/distfunctions
    q = wp.vec2(wp.length(wp.vec2(pos[0], pos[2])) - major_radius, pos[1])
    return wp.length(q) - minor_radius


@wp.func
def sdf_translate(pos: wp.vec3, offset: wp.vec3):
    """Translates a SDF position vector with an offset."""
    return pos - offset


@wp.func
def sdf_rotate(pos: wp.vec3, angles: wp.vec3):
    """Rotates a SDF position vector using Euler angles."""
    rot = wp.quat_rpy(
        wp.radians(angles[0]),
        wp.radians(angles[1]),
        wp.radians(angles[2]),
    )
    return wp.quat_rotate_inv(rot, pos)


@wp.func
def sdf_smooth_min(a: float, b: float, radius: float):
    """Creates a SDF torus primitive."""
    # https://iquilezles.org/articles/smin
    h = wp.max(radius - wp.abs(a - b), 0.0) / radius
    return wp.min(a, b) - h * h * h * radius * (1.0 / 6.0)


@wp.kernel(enable_backward=False)
def make_field(
    torus_altitude: float,
    torus_major_radius: float,
    torus_minor_radius: float,
    smooth_min_radius: float,
    dim: int,
    time: float,
    out_data: wp.array3d(dtype=float),
):
    """Kernel to generate a SDF volume based on primitives."""
    i, j, k = wp.tid()

    # Retrieve the position of the current cell in a normalized [-1, 1] range
    # for each dimension.
    pos = wp.vec3(
        2.0 * ((float(i) + 0.5) / float(dim)) - 1.0,
        2.0 * ((float(j) + 0.5) / float(dim)) - 1.0,
        2.0 * ((float(k) + 0.5) / float(dim)) - 1.0,
    )

    box = sdf_create_box(
        sdf_translate(pos, wp.vec3(0.0, -0.7, 0.0)),
        wp.vec3(0.9, 0.3, 0.9),
    )
    torus = sdf_create_torus(
        sdf_rotate(
            sdf_translate(pos, wp.vec3(0.0, torus_altitude, 0.0)),
            wp.vec3(wp.sin(time) * 90.0, wp.cos(time) * 45.0, 0.0),
        ),
        torus_major_radius,
        torus_minor_radius,
    )
    out_data[i, j, k] = sdf_smooth_min(box, torus, smooth_min_radius)


class Example:
    def __init__(self, stage: Optional[str]):
        self.dim = 64
        self.max_verts = int(1e6)
        self.max_tris = int(1e6)

        self.torus_altitude = -0.5
        self.torus_major_radius = 0.5
        self.torus_minor_radius = 0.1
        self.smooth_min_radius = 0.5

        self.fps = 60.0
        self.frame = 0

        self.field = wp.zeros((self.dim, self.dim, self.dim), dtype=float)
        self.mc = wp.MarchingCubes(self.dim, self.dim, self.dim, self.max_verts, self.max_tris)

        self.renderer = None
        if stage is not None:
            self.renderer = wp.render.UsdRenderer(stage)

    def step(self):
        with wp.ScopedTimer("Update Field"):
            wp.launch(
                make_field,
                dim=self.field.shape,
                inputs=(
                    self.torus_altitude,
                    self.torus_major_radius,
                    self.torus_minor_radius,
                    self.smooth_min_radius,
                    self.dim,
                    self.frame / self.fps,
                ),
                outputs=(self.field,),
            )

        with wp.ScopedTimer("Surface Extraction"):
            self.mc.surface(self.field, 0.0)

    def render(self):
        if self.renderer is None:
            return

        with wp.ScopedTimer("Render"):
            self.renderer.begin_frame(self.frame / self.fps)
            self.renderer.render_mesh(
                "surface",
                self.mc.verts.numpy(),
                self.mc.indices.numpy(),
                colors=((0.35, 0.55, 0.9),) * len(self.mc.verts),
                update_topology=True,
            )
            self.renderer.end_frame()


if __name__ == "__main__":
    this_file = os.path.basename(__file__).split(".")[0]
    stage_path = os.path.join(wp.examples.get_output_directory(), f"{this_file}.usd")

    example = Example(stage_path)
    for _ in range(240):
        example.step()
        example.render()
        example.frame += 1

    if example.renderer is not None:
        example.renderer.save()
